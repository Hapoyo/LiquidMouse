"""
🔨 Liquid Control Deployment Suite
Utility per la generazione dell'eseguibile standalone (EXE) per sistemi Windows.

Output: EXE/LiquidControl.exe (ultima build).
Con --pre: copia anche una candidate versionata in pre-release/.
Le release finali versionate vanno in release/ (gestite da release.py).
"""
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime

# Fix encoding console Windows (cp1252 non supporta emoji)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# Percorso assoluto della directory del progetto, indipendente dalla cwd di lancio
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

def _can_import(mod: str) -> bool:
    try:
        __import__(mod)
        return True
    except ImportError:
        return False

def check_files():
    """Verifica l'integrità dei componenti essenziali del progetto.

    Ogni asset elencato nel `datas` di LiquidControl.spec va elencato anche qui:
    un file mancante dal bundle non fa fallire la build, produce un EXE che
    risponde 404 solo a runtime — e solo sul percorso remoto.
    """
    required = [
        "server.pyw",
        "index.html",
        "xterm.js",
        "xterm.css",
        "icon.ico",
        os.path.join("liquidmouse", "version.py"),
        os.path.join("liquidmouse", "__init__.py"),
    ]
    missing = [f for f in required if not os.path.exists(os.path.join(SCRIPT_DIR, f))]
    
    if missing:
        print(f"❌ Errore Critico: Componenti mancanti: {', '.join(missing)}")
        return False
    return True

def build():
    print("="*50)
    print("   🖱️  LIQUID CONTROL - DEPLOYMENT UTILITY")
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

    # Verifica dipendenze runtime (required = abort se mancano, optional = warn)
    required_deps = [
        ("websockets",   "websockets"),
        ("pystray",      "pystray"),
        ("PIL",          "Pillow"),
        ("qrcode",       "qrcode"),
        ("cryptography", "cryptography"),
    ]
    optional_deps = [
        ("miniupnpc", "miniupnpc"),  # UPnP: richiede C compiler; disabilitato se assente
    ]
    missing_deps = [pkg for mod, pkg in required_deps if not _can_import(mod)]
    if missing_deps:
        print(f"   ⬇️  Installazione dipendenze mancanti: {', '.join(missing_deps)}")
        subprocess.check_call([sys.executable, "-m", "pip", "install"] + missing_deps)
    else:
        print("   ✅ Dipendenze runtime verificate.")
    for mod, pkg in optional_deps:
        if not _can_import(mod):
            print(f"   ⬇️  Installazione dipendenza opzionale: {pkg}")
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", pkg],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                print(f"   ✅ {pkg} installato.")
            except subprocess.CalledProcessError:
                print(f"   ⚠️  {pkg} non installabile (richiede C compiler). UPnP disabilitato nell'EXE.")

    # 2. Configurazione e Validazione
    if not check_files():
        return

    spec_file = os.path.join(SCRIPT_DIR, "LiquidControl.spec")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--clean",
        "--log-level", "WARN",
        "--distpath", "EXE",
        spec_file,
    ]

    # Rimozione preventiva: se il file è bloccato (app in esecuzione), fallisce qui
    # con messaggio chiaro invece di attendere l'errore criptico di PyInstaller
    exe_out = os.path.join("EXE", "LiquidControl.exe")
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
        exe_path = os.path.abspath(os.path.join("EXE", "LiquidControl.exe"))
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

        # --pre: archivia una candidate versionata in pre-release/
        if "--pre" in sys.argv:
            m = re.search(r'VERSION\s*=\s*"([^"]+)"',
                          open(os.path.join(SCRIPT_DIR, "liquidmouse", "version.py"),
                               encoding="utf-8").read())
            ver = m.group(1) if m else "dev"
            stamp = datetime.now().strftime("%Y%m%d-%H%M")
            pre_dir = os.path.join(SCRIPT_DIR, "pre-release")
            os.makedirs(pre_dir, exist_ok=True)
            pre_path = os.path.join(pre_dir, f"LiquidControl_v{ver}_pre_{stamp}.exe")
            shutil.copy2(exe_path, pre_path)
            print(f"📦 Candidate pre-release:\n   {pre_path}")

    except subprocess.CalledProcessError:
        print("\n❌ Errore fatale durante la fase di compilazione.")

if __name__ == "__main__":
    build()
    # isatty() può essere True anche con stdin chiuso (shell non interattive):
    # l'EOFError va comunque assorbito per non far fallire la build con exit 1
    if sys.stdin.isatty():
        try:
            input("\nPremere un tasto per terminare...")
        except EOFError:
            pass
