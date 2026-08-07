"""Interfaccia grafica (Tk) e icona nella tray.

**È l'unico sottopacchetto autorizzato a importare tkinter, pystray, PIL e
qrcode.** Tutto il resto di `liquidmouse/` deve restare importabile senza GUI e
senza Windows: è ciò che rende il core testabile in CI, e il workflow di test lo
verifica importando i moduli del core su Linux.

La dipendenza va in una direzione sola: la GUI conosce il core, il core non
conosce la GUI. Per mostrare un messaggio il core pubblica su
`liquidmouse.events`; qui ci si registra come sink.
"""
