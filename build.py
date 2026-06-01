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

    # Verifica dipendenze runtime
    runtime_deps = [
        ("websockets",   "websockets"),
        ("pystray",      "pystray"),
        ("PIL",          "Pillow"),
        ("qrcode",       "qrcode"),
        ("cryptography", "cryptography"),
        ("miniupnpc",    "miniupnpc"),
    ]
    missing_deps = []
    for mod, pkg in runtime_deps:
        try:
            __import__(mod)
        except ImportError:
            missing_deps.append(pkg)
    if missing_deps:
        print(f"   ⬇️  Installazione dipendenze mancanti: {', '.join(missing_deps)}")
        subprocess.check_call([sys.executable, "-m", "pip", "install"] + missing_deps)
    else:
        print("   ✅ Dipendenze runtime verificate.")

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
        exe_path = os.path.abspath(os.path.join("dist", "LiquidMouse.exe"))
        # Validazione post-build: EXE deve esistere e avere dimensione minima ragionevole
        if not os.path.exists(exe_path):
            print("\n❌ PyInstaller terminato con successo ma l'EXE non è stato generato.")
            return
        size_mb = os.path.getsize(exe_path) / (1024 * 1024)
        if size_mb < 5:
            print(f"\n⚠️  EXE generato ma dimensione anomala ({size_mb:.1f}MB). Verificare i moduli.")
        else:
            print(f"\n✅ OPERAZIONE COMPLETATA: Binario generato ({size_mb:.1f}MB).")
        print(f"\n📂 Percorso di output:\n   {exe_path}")

    except subprocess.CalledProcessError:
        print("\n❌ Errore fatale durante la fase di compilazione.")

if __name__ == "__main__":
    build()
    if sys.stdin.isatty():
        input("\nPremere un tasto per terminare...")
