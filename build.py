"""
🔨 Liquid Mouse Deployment Suite
Utility per la generazione dell'eseguibile standalone (EXE) per sistemi Windows.
"""
import os
import subprocess
import sys
import shutil

# Percorso assoluto della directory del progetto, indipendente dalla cwd di lancio
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

def check_files():
    """Verifica l'integrità dei componenti essenziali del progetto."""
    required = ["server.pyw", "index.html"]
    missing = [f for f in required if not os.path.exists(os.path.join(SCRIPT_DIR, f))]
    
    if missing:
        print(f"❌ Errore Critico: Componenti mancanti: {', '.join(missing)}")
        return False
    return True

def build():
    print("="*50)
    print("   🖱️  LIQUID MOUSE - DEPLOYMENT UTILITY")
    print("="*50)

    # Assicura che la cwd sia sempre la directory del progetto,
    # indipendentemente da dove viene lanciato lo script
    os.chdir(SCRIPT_DIR)
    print(f"   📂 Directory di lavoro: {SCRIPT_DIR}")

    # 1. Verifica infrastruttura di compilazione
    print("\n📦 Verifica ambiente PyInstaller...")
    try:
        import PyInstaller
        print("   ✅ Infrastruttura di compilazione rilevata.")
    except ImportError:
        print("   ⬇️  Installazione dei moduli necessari in corso...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    # 2. Configurazione e Validazione
    if not check_files():
        return

    # Definizione parametri PyInstaller
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconsole",              # Silenzia l'output del terminale utente
        "--onefile",                # Pacchetto eseguibile singolo
        "--name", "LiquidMouse",    # Identificativo dell'applicazione
        "--clean",                  # Svuotamento della cache di build
        "--log-level", "WARN",
        
        # Integrazione risorse statiche
        "--add-data", "index.html;.", 
    ]

    # Gestione asset grafici (Icona)
    if os.path.exists("icon.ico"):
        print("   🎨 Asset grafico rilevato: icon.ico")
        cmd.extend(["--icon", "icon.ico", "--add-data", "icon.ico;."])
    else:
        print("   ⚠️  Asset grafico (icona) non rilevato. Verrà utilizzata la risorsa di sistema predefinita.")

    cmd.append("server.pyw")

    # Gestione sovrascrittura versioni precedenti
    exe_out = os.path.join("dist", "LiquidMouse.exe")
    if os.path.exists(exe_out):
        try:
            os.remove(exe_out)
            print("   🗑️  Rimozione della versione precedente completata.")
        except OSError:
            print(f"\n❌ Errore di I/O: Impossibile sovrascrivere il binario esistente.")
            print("   ⚠️  Il processo 'Liquid Mouse' risulta attualmente in esecuzione. Terminare l'applicazione e riprovare.")
            return

    # 3. Processo di Compilazione
    print("\n🚀 Avvio del processo di build (la procedura potrebbe richiedere alcuni minuti)...")
    try:
        subprocess.check_call(cmd)
        print("\n✅ OPERAZIONE COMPLETATA: Binario generato con successo.")
        
        exe_path = os.path.abspath(os.path.join("dist", "LiquidMouse.exe"))
        print(f"\n📂 Percorso di output:\n   {exe_path}")
        
    except subprocess.CalledProcessError:
        print("\n❌ Errore fatale durante la fase di compilazione.")

if __name__ == "__main__":
    build()
    input("\nPremere un tasto per terminare la sessione...")
