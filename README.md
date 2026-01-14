# 🖱️ Liquid Mouse v1.3.2

Liquid Mouse trasforma il tuo smartphone in un touchpad wireless fluido e professionale per il tuo computer, operante interamente sulla rete Wi-Fi locale.

## ✨ Funzionalità Principali

* **Fluid Touch:** Movimento del cursore a bassa latenza.
* **Smart Scrolling:** Scorrimento inerziale ad alta sensibilità.
* **Funzioni Avanzate:** Drag & Drop, Seleziona Tutto (Ctrl+A), Tastiera Remota.
* **Server GUI:** Interfaccia moderna con supporto System Tray e Icone Personalizzate.
* **Privacy First:** Nessun cloud, funziona solo sulla rete locale.

## ⚠️ Limitazioni Importanti

* **Schermata di Login/Blocco:** A causa delle restrizioni di sicurezza di Windows (Secure Desktop), l'applicazione **non può interagire** con la schermata di login o quando il PC è bloccato. È necessario utilizzare un mouse/tastiera fisica per inserire la password. Una volta effettuato l'accesso, Liquid Mouse inizierà a funzionare immediatamente.

## 🛠️ Installazione e Setup

### 🖥️ Sistema Operativo Supportati

- ✅ Windows 10 / 11
- ✅ macOS (Intel e Apple Silicon)
- ✅ Linux (Ubuntu, Debian, Fedora, ecc.)

### 📋 Prerequisiti

1. **Python 3.7+**
   - Scarica da: https://python.org
   - ✅ Assicurati di spuntare "Add Python to PATH" durante l'installazione

2. **Smartphone con browser**
   - iOS: Safari
   - Android: Chrome, Firefox, Opera

3. **Connessione WiFi**
   - Computer e smartphone sulla stessa rete

### ⚡ Installazione Rapida (Windows)

```batch
# 1. Apri PowerShell/CMD nella cartella del progetto
# 2. Esegui:
python -m pip install --upgrade pip
pip install -r requirements.txt

# 3. Avvia il server:
python server.pyw

# 4. Dal telefono apri il link mostrato nel terminale
```

### 🍎 Installazione su macOS

```bash
# Usa Homebrew per Python (consigliato)
brew install python3

# O scarica da python.org

# Poi:
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Avvia:
python3 server.pyw
```

### 🐧 Installazione su Linux

```bash
# Debian/Ubuntu
sudo apt-get update
sudo apt-get install python3 python3-pip python3-venv

# Fedora
sudo dnf install python3 python3-pip

# Poi:
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Avvia:
python3 server.pyw
```

### 🔍 Verifica dell'Installazione

Esegui lo script di verifica:

**Windows:**
```batch
python verify.py
REM Oppure:
verify.bat
```

**macOS/Linux:**
```bash
python3 test.py
```

### 🚀 Primo Avvio

1. **Apri il terminale** nella cartella del progetto

2. **Esegui il server:**
   ```bash
   python server.pyw
   # o
   python3 server.pyw
   ```

3. **Vedrai un output come questo:**
   ```
   ==================================================
      🖱️  LIQUID MOUSE SERVER
   ==================================================
   📡 IP Locale: 192.168.1.100
   🔌 Porta: 8765
   🌐 WebSocket: ws://192.168.1.100:8765
   ==================================================

   📱 Apri questo link sul tuo smartphone:
      http://192.168.1.100:8000

   ⏳ In attesa di connessione...
   ==================================================
   ```

4. **Annota l'IP** (nel nostro esempio: `192.168.1.100`)

5. **Dal tuo smartphone:**
   - Apri il browser (Safari su iOS, Chrome su Android)
   - Digita: `http://192.168.1.100:8000` (sostituisci con il tuo IP)
   - Premi Invio

6. **Nella finestra di configurazione:**
   - L'IP dovrebbe essere già compilato
   - Se non è corretto, modificalo
   - Premi il pulsante **CONNETTI**

7. **Quando vedi "LINKED" in verde**, sei connesso! 🎉

### 🔧 Configurazione Post-Installazione

#### Sensibilità del Mouse

Modifica il valore `SENSITIVITY` in `server.pyw`:

```python
SENSITIVITY = 1.8  # Valore predefinito
```

- **Aumentare** (es: 2.5) = Mouse più veloce
- **Diminuire** (es: 0.8) = Mouse più lento

#### Porte Personalizzate

Se le porte 8765 o 8000 sono occupate, modificale in `server.pyw`:

```python
PORT = 8765        # Cambia il numero se occupato
HTTP_PORT = 8000   # Cambia il numero se occupato
```

#### Tema e Colori

Nel file `index.html`, modifica la sezione `:root`:

```css
:root {
    --bg-color: #2b2e4a;                     /* Blu scuro */
    --glass-surface: rgba(255,255,255,0.03); /* Trasparenza */
    --text-subtle: rgba(255,255,255,0.3);    /* Testo */
}
```

### 🐛 Troubleshooting Installazione

#### "Python non trovato"

**Soluzione:**
1. Scarica Python da https://python.org
2. Durante l'installazione, **spunta** "Add Python to PATH"
3. Riavvia il computer
4. Prova di nuovo

#### "ModuleNotFoundError: No module named 'websockets'"

**Soluzione:**
```bash
pip install websockets pyautogui
```

#### "Porta 8765 già in uso"

**Soluzione:**
```bash
# Windows
netstat -ano | findstr :8765
taskkill /PID <numero> /F

# macOS/Linux
lsof -i :8765
kill -9 <numero>
```

#### "ModuleNotFoundError: No module named 'pyautogui'"

**Soluzione:**
```bash
pip install pyautogui
```

### 📱 Accesso da Smartphone

#### 🔗 URL Corrette

- Stesso dispositivo (debug): `http://localhost:8000`
- Stessa rete: `http://192.168.1.100:8000`
- Rete diversa: Aggiungi SSL/TLS (vedi MANIFEST.md)

#### 🌐 Browser Compatibili

| Browser | iOS | Android | Note |
|---------|-----|---------|------|
| Safari | ✅ | - | iOS 13+ |
| Chrome | ✅ | ✅ | Consigliato |
| Firefox | ⚠️ | ✅ | Possibili problemi su iOS |
| Edge | ❌ | ✅ | Non testato su iOS |
| Opera | ❌ | ✅ | Funziona |

### 🎓 Prossimi Passi

Una volta installato:

1. Modifica la Configurazione Avanzata
2. Consulta CONTRIBUTING.md se vuoi contribuire

### 📚 Risorse Utili

- Documentazione Python
- WebSockets Library
- PyAutoGUI Reference
- MDN WebSocket API

## 📜 Changelog

Tutti i cambiamenti importanti a questo progetto saranno documentati qui.

### [1.3.2] - 2026-01-15 (Stability & Typing)
#### ✨ Aggiunto
- **Typing:** Supporto automatico per "smart quotes" (virgolette curve) da mobile.
- **Debounce:** Filtro anti-rimbalzo per il tasto Backspace (evita cancellazioni doppie involontarie).
- **Sicurezza:** Chiusura forzata pulita dell'applicazione (`os._exit`).

#### 🔧 Modificato
- **Docs:** Aggiornata documentazione con avvisi su Secure Desktop (Login Windows).
- **Core:** Ottimizzazione gestione percorsi e caricamento risorse.

### [1.2.0] - 2026-01-14 (Tray Edition)
#### ✨ Aggiunto
- **GUI (Interfaccia Grafica):** Sostituito il terminale nero con una finestra moderna in stile Liquid Mouse.
- **System Tray:** Il server ora si riduce a icona nella barra delle applicazioni invece di chiudersi.
- **Drag & Drop:** Nuovo pulsante "Lucchetto" per trascinare finestre e oggetti.
- **Select All:** Nuovo pulsante "SEL ALL" per selezionare tutto (Ctrl+A).

#### 🔧 Modificato
- **Scroll:** Aumentata notevolmente la sensibilità dello scroll verticale per maggiore fluidità.
- **Design:** Migliorata leggibilità nella pagina di configurazione (testo bianco su sfondo scuro).
- **Stabilità:** Aggiunto rilascio automatico del mouse in caso di disconnessione durante il trascinamento.

### [1.0.0] - 2026-01-12
#### ✨ Aggiunto
- Versione stabile iniziale del progetto.
- Server WebSocket base.
- Interfaccia web responsive.