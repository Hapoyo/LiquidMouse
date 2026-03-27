# LiquidMouse

Trasforma lo smartphone in touchpad e tastiera wireless per Windows.
Nessuna app da installare — il client gira nel browser.

## Requisiti

- Windows 10 / 11
- PC e smartphone sulla stessa rete Wi-Fi

## Installazione

**Eseguibile** — scarica `LiquidMouse.exe` dalla sezione [Releases](https://github.com/Hapoyo/LiquidMouse/releases).

**Da sorgente** — Python 3.7+:

```bash
pip install websockets pystray Pillow qrcode
python server.pyw
```

## Utilizzo

1. Avvia LiquidMouse sul PC
2. Scansiona il QR Code con lo smartphone o digita l'IP mostrato
3. Per chiudere: tray icon → Esci

## Funzionalità

- Touchpad con tap, doppio tap, long-press (click destro) e scroll a due dita
- Tastiera virtuale con supporto Unicode completo
- Menu rapido: Copia, Incolla, ESC, Ctrl/Shift lock, Drag lock, Seleziona tutto, Win, Play/Pausa
- Sensibilità cursore regolabile e salvata in locale
- Sicurezza: whitelist IP, solo rete locale, nessun cloud

## Risoluzione problemi

**Smartphone non si connette** — verifica che PC e telefono siano sulla stessa rete Wi-Fi e che il firewall Windows non blocchi le porte `8000` e `8765`.

**Porte occupate** — identifica il processo con `netstat -ano | findstr :8765`, poi terminalo con `taskkill /PID <id> /F`.

## Browser supportati

| Browser | iOS | Android |
| :--- | :---: | :---: |
| Chrome | ✅ | ✅ |
| Safari | ✅ | — |
| Firefox | ⚠️ | ✅ |
| Edge | — | ✅ |

## Licenza

GPL v3 — vedi [LICENSE](LICENSE)
