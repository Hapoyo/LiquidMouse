"""Porte di rete usate dall'applicazione.

La 8443 è la "porta unica" remota: serve sia il client statico sia il canale
comandi WSS. Molti router/ISP FWA lasciano passare 8443 ma filtrano porte
inusuali come la 8766, e un `wss://` su porta diversa fallisce in silenzio
perché il browser non mostra l'avviso sul certificato self-signed. Una porta
sola = un solo port-forward e un solo certificato da accettare.
"""

PORT       = 8765   # WS locale
HTTP_PORT  = 8000   # HTTP locale
HTTPS_PORT = 8443   # HTTPS remoto (con TLS) — pagina + WSS insieme
WSS_PORT   = 8766   # WSS remoto (con TLS) — legacy, client pre-porta-unica
