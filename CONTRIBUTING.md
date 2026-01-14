# 🤝 Contribuire a Liquid Mouse 

Grazie per l'interesse nel contribuire! Leggi questa guida per capire come aiutare.

---

## 📋 Come Contribuire

### 1. Segnalare Bug

Se trovi un bug:
1. Verifica che il problema non sia già stato segnalato
2. Descrivi il comportamento attuale e quello atteso
3. Fornisci i passi per riprodurre il problema
4. Includi informazioni su OS, versione Python e browser

**Esempio di buon bug report:**
```
Titolo: Mouse salta quando si sposta rapidamente

Descrizione:
Quando muovo il dito velocemente sul touchpad, il mouse "salta" 
in posizioni casuali invece di seguire il movimento fluido.

Passi per riprodurre:
1. Connettiti al server
2. Muovi il dito velocemente da sinistra a destra
3. Osserva il movimento del mouse

Ambiente:
- OS: Windows 11
- Python: 3.10
- Browser: Chrome su Android
- SENSITIVITY: 1.8
```

### 2. Suggerire Miglioramenti

Hai un'idea per migliorare il progetto?
1. Descrivi l'idea chiaramente
2. Spiega il caso d'uso
3. Fornisci esempi se possibile

**Idee apprezzate:**
- 🎮 Nuovi gesti o comandi
- 🎨 Miglioramenti UI/UX
- ⚡ Ottimizzazioni di performance
- 📚 Miglioramenti alla documentazione
- 🔐 Miglioramenti di sicurezza

### 3. Contribuire al Codice

#### Setup per lo Sviluppo

```bash
# Clona il repository
git clone https://github.com/tuoutente/liquid-mouse-pro.git
cd liquid-mouse-pro

# Crea un ambiente virtuale
python -m venv venv
source venv/bin/activate  # Su Windows: venv\Scripts\activate

# Installa le dipendenze
pip install -r requirements.txt

# Esegui i test
python test.py
```

#### Guida di Stile

**Python:**
- Usa nomi di funzione e variabile descrittivi
- Commenta codice complesso
- Massimo 80 caratteri per riga
- Usa 4 spazi per l'indentazione

**JavaScript/HTML:**
- Usa formato mobile-first
- Commenta le sezioni principali
- Segui le convenzioni camelCase
- Testa su diversi dispositivi

#### Processo di Contribuzione

1. **Fork** il repository
2. **Crea un branch** per la tua feature: `git checkout -b feature/mia-feature`
3. **Commit** i tuoi cambiamenti: `git commit -am 'Aggiungi mia feature'`
4. **Push** al branch: `git push origin feature/mia-feature`
5. **Apri una Pull Request** con una descrizione chiara

#### Checklist Prima del PR

- [ ] Ho testato le mie modifiche
- [ ] Ho verificato che non rompo le funzionalità esistenti
- [ ] Ho aggiunto commenti dove necessario
- [ ] Ho aggiornato il README se ho cambiato il comportamento
- [ ] Ho eseguito `python test.py` con successo

---

## 📁 Struttura del Codice

### Backend (server.py)

```python
# Funzioni principali:
- get_local_ip()        # Recupera l'IP locale
- async handler()       # Gestisce i messaggi WebSocket
- handle_move()         # Movimento del mouse
- handle_click()        # Click del mouse
- handle_text()         # Input di testo
```

### Frontend (index.html)

```javascript
// Classi principali:
- ConfigPanel           // Pannello di configurazione
- ControlPanel          // Pannello di controllo principale
- Touchpad              // Gestione del touchpad
- WebSocketManager      // Gestione connessione WebSocket
```

---

## 🧪 Testing

Prima di contribuire, assicurati che:

```bash
# 1. Il server non ha errori di sintassi
python -m py_compile server.pyw

# 2. Lo script test passa
python test.py

# 3. Testa manualmente l'avvio
python server.pyw

## 📝 Documentazione

Se aggiungi una nuova feature:
1. Documenta il codice con commenti chiari
2. Aggiorna il README.md se necessario
3. Aggiungi un esempio di utilizzo

---

## 🎯 Priorità di Sviluppo

**Alta priorità:**
- 🐛 Bug fixes critici
- 🔐 Problemi di sicurezza
- ⚡ Problemi di performance

**Media priorità:**
- ✨ Nuove feature utili
- 📚 Miglioramenti documentazione
- 🎨 Miglioramenti UI

**Bassa priorità:**
- 💄 Cambiamenti cosmetici
- 🎉 Feature nice-to-have

---

## 💬 Codice di Condotta

Per mantenere un ambiente positivo:
- ✅ Sii rispettoso e inclusivo
- ✅ Dai feedback costruttivo
- ✅ Ascolta altre opinioni
- ❌ Niente spam o abuso
- ❌ Niente discriminazioni

---

## 🏆 Riconoscimenti

Apprezziamo molto i vostri contributi! Sarete riconosciuti nel:
- README.md (sezione Contribuenti)
- Changelog
- Release notes

---

## ❓ Domande?

Se hai domande:
1. Controlla il README.md
2. Apri una discussion
3. Contattami direttamente

---

**Grazie per aver scelto di contribuire! 🙏**

