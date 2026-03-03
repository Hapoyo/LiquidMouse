# 🖱️ Liquid Mouse v1.6.0 (Enhanced Input Edition)

Liquid Mouse trasforma il tuo smartphone in un touchpad wireless fluido e professionale per il tuo computer, operante interamente sulla rete Wi-Fi locale.

## ✨ Funzionalità Principali

* **Fluid Touch:** Movimento del cursore a bassa latenza.
* **Smart Menu:** Menu centrale a comparsa con strumenti rapidi e Clipboard (Copia/Incolla).
* **Smart Scrolling:** Scorrimento inerziale ad alta sensibilità.
* **Funzioni Avanzate:** Drag & Drop, Seleziona Tutto (Ctrl+A), Tastiera Remota.
* **Server GUI:** Interfaccia moderna con supporto System Tray e Icone Personalizzate.
* **Privacy First:** Nessun cloud, funziona solo sulla rete locale.

## ⚠️ Limitazioni Importanti

* **Schermata di Login/Blocco:** A causa delle restrizioni di sicurezza di Windows (Secure Desktop), l'applicazione **non può interagire** con la schermata di login o quando il PC è bloccato. È necessario utilizzare un mouse/tastiera fisica per inserire la password. Una volta effettuato l'accesso, Liquid Mouse inizierà a funzionare immediatamente.

## 🚀 Guida Rapida

### Prerequisiti Minimi

- **Python 3.7+** installato
- **Smartphone** con browser web
- **WiFi:** Computer e smartphone sulla stessa rete

### ⚡ Avvio Immediato

1. **Apri il terminale** nella cartella del progetto

2. **Esegui:**

   ```
   python server.pyw        # Windows
   python3 server.pyw       # macOS/Linux
   ```

3. **Vedrai:**

   ```
   ==================================================
      🖱️  LIQUID MOUSE SERVER
   ==================================================
   📡 IP: 192.168.1.100
   📱 Apri nel telefono: http://192.168.1.100:8000
   ==================================================
   ```

4. **Dal telefono:** Apri il browser, inserisci l'IP e connettiti

5. **Pronto!** 🎉 Usa lo schermo come touchpad

### 🖥️ Sistemi Supportati

- Windows 10/11
- macOS (Intel/Apple Silicon)
- Linux (Ubuntu, Debian, Fedora, ecc.)

### 🐛 Troubleshooting

#### "Python non trovato"

- Scarica da https://python.org
- Spunta "Add Python to PATH" durante l'installazione

#### "Porta 8765 o 8000 occupata"

**Windows:**

```
netstat -ano | findstr :8765
taskkill /PID <numero> /F
```

**macOS/Linux:**

```
lsof -i :8765
kill -9 <numero>
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

## 📜 Changelog

Tutti i cambiamenti importanti a questo progetto saranno documentati qui.

### [1.5.0] - 2026-01-17 (Terminal Edition)

#### ✨ Aggiunto

- **Terminal GUI:** Nuova interfaccia server in stile terminale virtuale con animazioni di boot.
- **Design System:** Aggiornato il tema grafico a "Terminal Dark" (Nero/Verde) su tutti i dispositivi.

### [1.4.0] - 2026-01-16 (Smart Menu Edition)

#### ✨ Aggiunto

- **Smart Menu:** Nuovo pulsante centrale che apre un menu a raggiera con gli strumenti.
- **Clipboard:** Aggiunti pulsanti Copia (Ctrl+C) e Incolla (Ctrl+V) nel menu centrale.
- **UI:** Layout ottimizzato con margini ridotti per avvicinare i controlli al touchpad.

#### 🔧 Modificato

- **UX:** Raggruppati i tasti Tastiera, Drag e Select All nel nuovo menu per pulire l'interfaccia principale.

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
* Server WebSocket base.
* Interfaccia web responsive.
