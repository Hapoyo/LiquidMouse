"""
🔨 Liquid Mouse Deployment Suite
Utility per la generazione dell'eseguibile standalone (EXE) per sistemi Windows.
"""
import os
import subprocess
import sys

# Fix encoding console Windows (cp1252 non supporta emoji)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

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

    spec_file = os.path.join(SCRIPT_DIR, "LiquidMouse.spec")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--clean",
        "--log-level", "WARN",
        spec_file,
    ]

    # Rimozione preventiva: se il file è bloccato (app in esecuzione), fallisce qui
    # con messaggio chiaro invece di attendere l'errore criptico di PyInstaller
    exe_out = os.path.join("dist", "LiquidMouse.exe")
    try:
        os.remove(exe_out)
        print("   🗑️  Versione precedente rimossa.")
    except FileNotFoundError:
        pass
    except OSError:
        print("\n❌ Impossibile sovrascrivere il binario: l'applicazione è in esecuzione. Chiuderla e riprovare.")
        return

    # 3. Processo di Compilazione
    print("\n🚀 Avvio del processo di build (la procedura potrebbe richiedere alcuni minuti)...")
    try:
        subprocess.check_call(cmd, cwd=SCRIPT_DIR)
        print("\n✅ OPERAZIONE COMPLETATA: Binario generato con successo.")
        
        exe_path = os.path.abspath(os.path.join("dist", "LiquidMouse.exe"))
        print(f"\n📂 Percorso di output:\n   {exe_path}")
        
    except subprocess.CalledProcessError:
        print("\n❌ Errore fatale durante la fase di compilazione.")

if __name__ == "__main__":
    build()
    if sys.stdin.isatty():
        input("\nPremere un tasto per terminare...")
