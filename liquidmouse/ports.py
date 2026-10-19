"""Porte di rete usate dall'applicazione.

La 8443 è la "porta unica" remota: serve sia il client statico sia il canale
comandi WSS. Molti router/ISP FWA lasciano passare 8443 ma filtrano porte
inusuali, e un `wss://` su porta diversa fallisce in silenzio perché il
browser non mostra l'avviso sul certificato self-signed. Una porta sola = un
solo port-forward e un solo certificato da accettare. (La vecchia 8766, un WSS
dedicato per i client precedenti alla porta unica, è stata rimossa.)
"""

PORT       = 8765   # WS locale
HTTP_PORT  = 8000   # HTTP locale
HTTPS_PORT = 8443   # HTTPS remoto (con TLS) — pagina + WSS insieme
# Origine del tunnel Cloudflare: solo 127.0.0.1, ci si collega cloudflared.
# Porta a sé perché da qui tutti i client arrivano come loopback, che sulle
# altre porte è fidato senza PIN: su questa il PIN è sempre obbligatorio.
TUNNEL_PORT = 8767
