"""Certificato TLS auto-firmato per il percorso remoto.

Il client remoto arriva via HTTPS/WSS su una porta pubblica, quindi serve un
certificato. Non essendoci un dominio, è auto-firmato con l'IP nel SAN: il
browser mostra l'avviso una volta e poi si accetta.

Il certificato è salvato in config e riusato fra un avvio e l'altro. Rigenerarlo
a ogni avvio costringerebbe ad accettare di nuovo l'avviso ogni volta.
"""

import atexit
import ipaddress
import os
import ssl
import tempfile

from liquidmouse.events import log_message
from liquidmouse.theme import COLOR_ERROR

CERT_VALIDITY_DAYS = 3650
RSA_KEY_SIZE = 2048


class SelfSignedCert:
    """Gestisce il certificato e il relativo SSLContext.

    `config` è un liquidmouse.config.Config: qui vengono letti e scritti
    `ssl_cert`, `ssl_key` e `ssl_ip`.
    """

    def __init__(self, config) -> None:
        self._config = config
        self._context: ssl.SSLContext | None = None
        self._temp_files: list[str] = []
        self._atexit_registered = False

    def context_for(self, local_ip: str) -> ssl.SSLContext | None:
        """SSLContext valido per `local_ip`, None se non è stato possibile.

        Ritorna None invece di sollevare: senza TLS l'app resta usabile in LAN,
        solo il percorso remoto non parte.
        """
        if self._context and self._config.get('ssl_ip') == local_ip:
            return self._context
        try:
            cert_pem, key_pem = self._materiale(local_ip)
            return self._build_context(cert_pem, key_pem)
        except ImportError:
            # Senza cryptography niente 8443/8766. Va detto: il sintomo
            # altrimenti e' solo un client remoto fermo su "IN ATTESA".
            log_message("TLS non disponibile: manca 'cryptography'", color=COLOR_ERROR)
            return None
        except Exception as e:
            log_message(f"Certificato TLS non generato: {e}", color=COLOR_ERROR)
            return None

    def _materiale(self, local_ip: str) -> tuple[bytes, bytes]:
        """Certificato e chiave in PEM, dalla config o generati ora."""
        if (self._config.get('ssl_cert') and self._config.get('ssl_key')
                and self._config.get('ssl_ip') == local_ip):
            return (self._config['ssl_cert'].encode(),
                    self._config['ssl_key'].encode())
        return self._genera(local_ip)

    def _genera(self, local_ip: str) -> tuple[bytes, bytes]:
        """Genera una nuova coppia e la salva in config.

        La generazione della chiave RSA richiede qualche secondo: capita al
        primo avvio e quando cambia l'IP locale, non a ogni avvio.
        """
        import datetime

        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID

        key = rsa.generate_private_key(public_exponent=65537, key_size=RSA_KEY_SIZE)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "LiquidControl")])
        try:
            san = x509.SubjectAlternativeName([
                x509.IPAddress(ipaddress.ip_address(local_ip))])
        except ValueError:
            san = x509.SubjectAlternativeName([x509.DNSName(local_ip)])
        # utcnow() e' deprecata da Python 3.12, ma cryptography interpreta come
        # UTC i datetime naive e questo e' il comportamento gia' collaudato in
        # produzione: passare a un datetime aware qui cambierebbe l'input di una
        # libreria di terze parti senza alcun beneficio.
        now = datetime.datetime.utcnow()
        cert = (
            x509.CertificateBuilder()
            .subject_name(name).issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now)
            .not_valid_after(now + datetime.timedelta(days=CERT_VALIDITY_DAYS))
            .add_extension(san, critical=False)
            .sign(key, hashes.SHA256())
        )
        cert_pem = cert.public_bytes(serialization.Encoding.PEM)
        key_pem = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
        self._config['ssl_cert'] = cert_pem.decode()
        self._config['ssl_key'] = key_pem.decode()
        self._config['ssl_ip'] = local_ip
        self._config.save()
        return cert_pem, key_pem

    def _build_context(self, cert_pem: bytes, key_pem: bytes) -> ssl.SSLContext:
        """load_cert_chain vuole dei percorsi, non dei byte: servono file temporanei."""
        self._cleanup_temps()
        cf = tempfile.NamedTemporaryFile(delete=False, suffix='.crt', mode='wb')
        cf.write(cert_pem)
        cf.close()
        kf = tempfile.NamedTemporaryFile(delete=False, suffix='.key', mode='wb')
        kf.write(key_pem)
        kf.close()
        self._temp_files = [cf.name, kf.name]
        if not self._atexit_registered:
            atexit.register(self._cleanup_temps)
            self._atexit_registered = True

        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cf.name, kf.name)
        self._context = ctx
        return ctx

    def _cleanup_temps(self) -> None:
        """Rimuove i file temporanei: contengono la chiave privata."""
        for path in self._temp_files:
            try:
                if os.path.exists(path):
                    os.unlink(path)
            except OSError:
                pass
