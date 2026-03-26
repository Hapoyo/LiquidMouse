# LiquidMouse

Trasforma lo smartphone in un touchpad e tastiera wireless per Windows.
Il server gira sul PC, il client si apre nel browser del telefono — nessuna app da installare.

## Requisiti

- Windows 10 / 11
- PC e smartphone sulla stessa rete Wi-Fi
- Browser moderno (Chrome o Safari consigliati)

## Installazione

**Eseguibile** — scarica l'ultima versione dalla sezione [Releases](https://github.com/Hapoyo/LiquidMouse/releases) ed esegui `LiquidMouse.exe`.

**Da sorgente** — Python 3.7+:

```bash
pip install websockets pystray Pillow qrcode
python server.pyw
```

## Utilizzo

1. Avvia LiquidMouse sul PC
2. Scansiona il QR Code con lo smartphone (o digita l'URL)
3. Usa il touchpad nella pagina che si apre
4. Per chiudere: tasto destro sull'icona nella system tray → Esci

## Funzionalità

- Touchpad con tap, doppio tap e long-press (click destro)
- Scroll a due dita
- Tastiera virtuale integrata
- Sensibilità del cursore regolabile
- Menu rapido: Copia, Incolla, Ctrl, Shift, Drag, Seleziona tutto, ESC
- Whitelist IP — solo il primo dispositivo connesso viene autorizzato
- Solo rete locale, nessun cloud

## Risoluzione problemi

**Lo smartphone non si connette** — verifica che PC e telefono siano sulla stessa rete Wi-Fi e che il firewall di Windows non blocchi le porte 8765 e 8000.

**Porte occupate** — libera i processi con `netstat -ano | findstr :8765`, poi `taskkill /PID <id> /F`.

## Browser supportati

| Browser | iOS | Android |
| :--- | :---: | :---: |
| Chrome | ✅ | ✅ |
| Safari | ✅ | — |
| Firefox | ⚠️ | ✅ |
| Edge | — | ✅ |

## Licenza

GPL v3 — vedi [LICENSE](LICENSE)
