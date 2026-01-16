# 🤝 Contribuire a Liquid Mouse

Grazie per l'interesse nel contribuire! Liquid Mouse è un progetto open source e accogliamo con favore ogni tipo di supporto, dalla segnalazione di bug alla scrittura di codice.

---

## 🛠️ Setup dell'Ambiente di Sviluppo

Per modificare il codice o creare una tua versione personalizzata dell'eseguibile, segui questi passi.

### 1. Preparazione

```bash
# Clona il repository
git clone [https://github.com/tuoutente/liquid-mouse.git](https://github.com/tuoutente/liquid-mouse.git)
cd liquid-mouse

# Crea un ambiente virtuale (Best Practice)
python -m venv venv

# Attiva l'ambiente
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# Installa le dipendenze
pip install -r requirements.txt
2. Eseguire in modalità Sviluppo
Non è necessario compilare ogni volta. Per testare le modifiche al volo:

Bash

python server.pyw
📦 Creare l'Eseguibile (Build)
Se hai apportato modifiche al codice e vuoi generare un nuovo file LiquidMouse.exe da distribuire (o per uso personale senza Python), abbiamo incluso uno script automatico.

Prerequisiti Build
Assicurati di aver installato le dipendenze, lo script installerà automaticamente pyinstaller se manca.

Procedura di Build
Assicurati di essere nella cartella radice del progetto.

Assicurati che server.pyw e index.html siano presenti.

Esegui lo script di build:

Bash

python build.py
Attendi il completamento.

Troverai il tuo nuovo eseguibile nella cartella dist/.

Nota: Se l'applicazione è in esecuzione, chiudila prima di avviare la build, altrimenti la sovrascrittura del file .exe fallirà.

🧪 Testing
Prima di inviare una Pull Request, assicurati che:

Sintassi: Il codice Python non abbia errori di sintassi.

Bash

python -m py_compile server.pyw
Test Funzionale: Esegui python test.py per verificare le dipendenze.

Test Build: Se hai modificato le importazioni o i file statici, prova a eseguire python build.py e verifica che l'.exe generato si avvii correttamente.

📁 Struttura del Codice
server.pyw: Il cuore dell'applicazione. Gestisce il server WebSocket, l'interfaccia GUI Tkinter (la finestra terminale) e l'icona nella System Tray.

index.html: Il frontend che viene caricato sullo smartphone. Include CSS e JS in un unico file per semplicità di distribuzione.

build.py: Script di utilità per compilare il progetto con PyInstaller.

🐛 Segnalare Bug
Se trovi un bug, apri una Issue includendo:

Se stai usando l'EXE o la versione Python.

Il tuo sistema operativo (es. Windows 11).

Il browser usato sullo smartphone.

I passi per riprodurre l'errore.

Grazie per il tuo aiuto! 🙏
