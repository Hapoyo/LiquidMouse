import json

# Contenuto del Notebook
notebook_content = {
 "cells": [
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "# 🖱️ Liquid Mouse - Developer Playground\n",
    "\n",
    "Benvenuto nel notebook di sviluppo di **Liquid Mouse**. \n",
    "Usa questo file per testare le funzionalità, verificare le dipendenze e capire come funziona il codice backend.\n",
    "\n",
    "### ⚠️ Attenzione\n",
    "L'esecuzione delle celle di movimento mouse prenderà il controllo del tuo cursore per qualche secondo. Tieniti pronto!"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": None,
   "metadata": {},
   "outputs": [],
   "source": [
    "# 1. Installazione/Verifica Dipendenze\n",
    "# Esegui questa cella per assicurarti di avere tutto il necessario.\n",
    "\n",
    "import sys\n",
    "!{sys.executable} -m pip install websockets pyautogui pystray Pillow\n",
    "\n",
    "print(\"\\n✅ Dipendenze verificate.\")"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": None,
   "metadata": {},
   "outputs": [],
   "source": [
    "# 2. Configurazione e Importazioni\n",
    "import pyautogui\n",
    "import socket\n",
    "import time\n",
    "\n",
    "# Configurazioni di sicurezza per i test\n",
    "pyautogui.FAILSAFE = True  # Sposta il mouse nell'angolo in alto a sinistra per abortire\n",
    "pyautogui.PAUSE = 0.1\n",
    "\n",
    "print(\"Librerie importate e configurate.\")"
   ]
  },
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "## 🧪 Test Diagnostici"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": None,
   "metadata": {},
   "outputs": [],
   "source": [
    "# 3. Verifica IP Locale\n",
    "# Questo è l'IP che userai per connetterti dal telefono.\n",
    "\n",
    "def get_local_ip():\n",
    "    try:\n",
    "        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)\n",
    "        s.connect((\"8.8.8.8\", 80))\n",
    "        ip = s.getsockname()[0]\n",
    "        s.close()\n",
    "        return ip\n",
    "    except Exception as e:\n",
    "        return f\"Errore: {e}\"\n",
    "\n",
    "print(f\"📡 Il tuo IP Locale è: {get_local_ip()}\")"
   ]
  },
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "## 🖱️ Test Automazione (PyAutoGUI)\n",
    "Le celle seguenti muoveranno fisicamente il tuo mouse. Assicurati di avere spazio sullo schermo."
   ]
  },
  {
   "cell_type": "code",
   "execution_count": None,
   "metadata": {},
   "outputs": [],
   "source": [
    "# 4. Test Movimento (Disegna un quadrato)\n",
    "print(\"Disegno un quadrato tra 3 secondi...\")\n",
    "time.sleep(3)\n",
    "\n",
    "distance = 200\n",
    "try:\n",
    "    pyautogui.moveRel(distance, 0, duration=0.5)   # Destra\n",
    "    pyautogui.moveRel(0, distance, duration=0.5)   # Giù\n",
    "    pyautogui.moveRel(-distance, 0, duration=0.5)  # Sinistra\n",
    "    pyautogui.moveRel(0, -distance, duration=0.5)  # Su\n",
    "    print(\"✅ Test movimento completato.\")\n",
    "except pyautogui.FailSafeException:\n",
    "    print(\"🛑 Test interrotto dall'utente (Failsafe).\")"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": None,
   "metadata": {},
   "outputs": [],
   "source": [
    "# 5. Test Scrittura\n",
    "# Clicca su questa cella di output o apri un notepad prima che finisca il countdown\n",
    "\n",
    "print(\"Scriverò un messaggio tra 5 secondi. Seleziona un campo di testo!\")\n",
    "time.sleep(5)\n",
    "pyautogui.write(\"Ciao da Liquid Mouse! 🖱️\", interval=0.1)\n",
    "print(\"✅ Test scrittura completato.\")"
   ]
  },
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "## 🌐 Test Server (Sperimentale)\n",
    "Puoi avviare il server WebSocket direttamente qui. \n",
    "**Nota:** Per fermarlo, dovrai interrompere il Kernel del notebook (Stop)."
   ]
  },
  {
   "cell_type": "code",
   "execution_count": None,
   "metadata": {},
   "outputs": [],
   "source": [
    "# 6. Avvio Server in Notebook\n",
    "import asyncio\n",
    "import websockets\n",
    "import json\n",
    "\n",
    "PORT = 8765\n",
    "\n",
    "async def handler(websocket):\n",
    "    print(\"Client connesso!\")\n",
    "    try:\n",
    "        async for message in websocket:\n",
    "            data = json.loads(message)\n",
    "            print(f\"Ricevuto: {data}\")\n",
    "            # Qui inseriresti la logica di PyAutoGUI...\n",
    "    except websockets.exceptions.ConnectionClosed:\n",
    "        print(\"Client disconnesso\")\n",
    "\n",
    "print(f\"⏳ Avvio server su ws://0.0.0.0:{PORT}...\")\n",
    "print(\"Premi STOP sul Kernel per fermare.\")\n",
    "\n",
    "# In Jupyter, il loop eventi è già attivo, quindi usiamo 'await' direttamente\n",
    "# invece di asyncio.run()\n",
    "try:\n",
    "    async with websockets.serve(handler, \"0.0.0.0\", PORT):\n",
    "        await asyncio.Future()  # run forever\n",
    "except Exception as e:\n",
    "    print(f\"Server fermato: {e}\")"
   ]
  }
 ],
 "metadata": {
  "kernelspec": {
   "display_name": "Python 3",
   "language": "python",
   "name": "python3"
  },
  "language_info": {
   "codemirror_mode": {
    "name": "ipython",
    "version": 3
   },
   "file_extension": ".py",
   "mimetype": "text/x-python",
   "name": "python",
   "nbconvert_exporter": "python",
   "pygments_lexer": "ipython3",
   "version": "3.8.5"
  }
 },
 "nbformat": 4,
 "nbformat_minor": 4
}

# Scrittura del file
with open('LiquidMouse_Playground.ipynb', 'w', encoding='utf-8') as f:
    json.dump(notebook_content, f, indent=1)

print("✅ File 'LiquidMouse_Playground.ipynb' creato con successo!")
