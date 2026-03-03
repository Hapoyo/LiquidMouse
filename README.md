# 🖱️ Liquid Mouse

Liquid Mouse è una soluzione software avanzata progettata per trasformare il proprio dispositivo mobile in un'interfaccia di input wireless (touchpad) ad alte prestazioni. Il sistema opera esclusivamente all'interno della rete locale (LAN), garantendo elevati standard di privacy e prestazioni in tempo reale.

## 🛠️ Caratteristiche Principali

* **Controllo Cursore a Bassa Latenza:** Utilizza lo smartphone come un touchpad reattivo.
* **Connessione Immediata tramite QR Code:** Collega il dispositivo scansionando il codice QR generato dal server.
* **Menu Rapido e Scorciatoie:** Accesso diretto a funzioni essenziali come Copia, Incolla e Seleziona Tutto.
* **Scroll Fluido:** Scorrimento integrato per la navigazione dei documenti.
* **Input Avanzato:** Supporto per trascinamento (Drag & Drop) e digitazione da tastiera remota.
* **Modalità Background:** Il server può operare in modo silenzioso tramite la System Tray.
* **Nessun Cloud:** L'intera comunicazione avviene localmente (LAN), garantendo massima privacy.

## ⚠️ Note Sulla Sicurezza e Limitazioni

* **Restrizioni Secure Desktop:** In conformità con i protocolli di sicurezza di Microsoft Windows (Secure Desktop), l'applicazione non dispone dei privilegi necessari per interagire con le schermate di sistema critiche, come il login o il blocco utente. L'operatività standard riprende automaticamente una volta effettuato l'accesso al sistema.

## 🚀 Guida all'Installazione e Configurazione

### Requisiti Minimi di Sistema

* **Runtime:** Python 3.7 o versioni successive.
* **Client:** Dispositivo mobile dotato di browser web moderno.
* **Rete:** Connettività Wi-Fi condivisa tra Host (PC) e Client (Smartphone).

### ⚡ Procedure di Avvio

#### Opzione 1: Eseguibile Binario (Consigliato per Windows)

1. **Download:** Prelevare l'ultima release stabile dalla sezione [Releases](https://github.com/tuonome/LiquidMouse/releases).
2. **Estrazione:** Decomprimere l'archivio e individuare il file `.exe`.
3. **Inizializzazione:** Eseguire l'applicazione per avviare il servizio server.
4. **Connessione Client:** Inquadrare il **QR Code** mostrato sulla console con la fotocamera dello smartphone oppure accedere all'URL specificato.

#### Opzione 2: Esecuzione tramite Sorgente (Cross-platform)

1. Posizionarsi nella directory radice del progetto tramite terminale.
2. Installare le dipendenze necessarie: `pip install pystray Pillow qrcode`
3. Avviare il servizio utilizzando il comando appropriato per il sistema operativo in uso:
    * **Windows:** `python server.pyw`
    * **macOS/Linux:** `python3 server.pyw`
4. L'interfaccia mostrerà un **QR Code** e le credenziali di rete per la connessione:

    ```text
    ==================================================
       🖱️  LIQUID MOUSE SERVER CONTROL
    ==================================================
    📡 Host IP: 192.168.1.100
    📱 Access URL: http://192.168.1.100:8000
    [ QR CODE VISIBILE NELLA GUI ]
    ==================================================
    ```

5. Scansionare il QR Code o inserire l'URL nel browser del dispositivo mobile per stabilire il collegamento.

## 🖥️ Compatibilità Sistemi Operativi

* Microsoft Windows 10/11
* Apple macOS (Intel e Apple Silicon)
* Distribuzioni Linux (Ubuntu, Debian, Fedora e derivate)

## 🛠️ Risoluzione Problemi (Troubleshooting)

### Assenza del Runtime Python

* Consultare il portale ufficiale [python.org](https://python.org).
* Assicurarsi di selezionare l'opzione "Add Python to PATH" durante la fase di installazione.

### Conflitti di Rete (Porte Occupate)

Nel caso in cui le porte 8765 o 8000 risultino già impegnate da altri processi:

**Windows:**

```powershell
netstat -ano | findstr :8765
taskkill /PID <numero_processo> /F
```

**macOS/Linux:**

```bash
lsof -i :8765
kill -9 <pid_processo>
```

## 📱 Dettagli sulla Connettività Mobile

### Protocolli di Indirizzamento

* **Ambiente di test:** `http://localhost:8000`
* **Rete Locale Standard:** `http://192.168.x.x:8000`
* **Connessioni Sicure:** Per implementazioni SSL/TLS, fare riferimento al file `MANIFEST.md`.

### Browser Supportati

| Browser | iOS | Android | Note |
| :--- | :---: | :---: | :--- |
| **Safari** | ✅ | - | Richiede iOS 13+ |
| **Chrome** | ✅ | ✅ | Raccomandato per stabilità |
| **Firefox** | ⚠️ | ✅ | Possibili limitazioni su iOS |
| **Edge** | ❌ | ✅ | Supporto in fase di test su iOS |
| **Opera** | ❌ | ✅ | Funzionalità standard verificata |

---
© 2026 Liquid Mouse Project - Sviluppato per l'eccellenza operativa.
