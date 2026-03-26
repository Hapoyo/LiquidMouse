"""
LiquidMouse - Script di Rilascio
Automatizza: bump versione → commit → tag → push su GitHub
"""
import os
import re
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_FILE = os.path.join(SCRIPT_DIR, "server.pyw")
REMOTE = "origin"
BRANCH = "main"


def run(cmd, check=True):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=SCRIPT_DIR)
    if check and result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def check_git():
    try:
        run("git rev-parse --git-dir")
        return True
    except RuntimeError:
        return False


def get_current_version():
    content = open(SERVER_FILE, encoding="utf-8").read()
    m = re.search(r'VERSION\s*=\s*"([^"]+)"', content)
    if not m:
        print("❌ Versione non trovata in server.pyw")
        sys.exit(1)
    return m.group(1)


def bump_version(version):
    parts = version.split(".")
    parts[-1] = str(int(parts[-1]) + 1)
    return ".".join(parts)


def set_version(new_version):
    content = open(SERVER_FILE, encoding="utf-8").read()
    updated = re.sub(r'VERSION\s*=\s*"[^"]+"', f'VERSION = "{new_version}"', content)
    open(SERVER_FILE, "w", encoding="utf-8").write(updated)


def get_changed_files():
    out = run("git status --porcelain", check=False)
    return [line[3:].strip() for line in out.splitlines() if line.strip()]


def main():
    print("=" * 50)
    print("   🖱️  LIQUID MOUSE - SCRIPT DI RILASCIO")
    print("=" * 50)

    os.chdir(SCRIPT_DIR)

    # Verifica git
    if not check_git():
        print("\n❌ Git non disponibile in questa directory.")
        print("   Assicurati di trovarti in un repository git inizializzato.")
        print(f"   Esegui: git init && git remote add origin <url>")
        sys.exit(1)

    # Versione attuale
    current = get_current_version()
    suggested = bump_version(current)

    print(f"\n📌 Versione attuale: {current}")
    new_version = input(f"   Nuova versione [{suggested}]: ").strip() or suggested

    # Aggiorna version in server.pyw
    set_version(new_version)
    print(f"\n✅ Versione aggiornata a {new_version} in server.pyw")

    # Mostra file modificati
    changed = get_changed_files()
    if not changed:
        print("\n⚠️  Nessun file modificato rilevato da git.")
    else:
        print(f"\n📝 File modificati:")
        for f in changed:
            print(f"   - {f}")

    # Conferma
    print()
    confirm = input("Procedere con commit, tag e push? [S/n]: ").strip().lower()
    if confirm in ("n", "no"):
        print("❌ Operazione annullata.")
        sys.exit(0)

    tag = f"v{new_version}"
    commit_msg = f"release: {tag}"

    try:
        # Stage tutti i file tracciati modificati
        run("git add -u")
        # Stage anche release.py se non tracciato
        run("git add release.py", check=False)

        # Commit
        run(f'git commit -m "{commit_msg}"')
        print(f"✅ Commit: \"{commit_msg}\"")

        # Tag
        run(f"git tag {tag}")
        print(f"✅ Tag creato: {tag}")

        # Push branch
        run(f"git push {REMOTE} {BRANCH}")
        print(f"✅ Push su {REMOTE}/{BRANCH}")

        # Push tag (attiva GitHub Actions → build EXE)
        run(f"git push {REMOTE} {tag}")
        print(f"✅ Push tag {tag} → GitHub Actions avviato")

        print(f"\n🎉 Rilascio {tag} completato!")
        print(f"   GitHub Actions costruirà LiquidMouse_v{new_version}.exe automaticamente.")
        print(f"   Controlla: https://github.com/Hapoyo/LiquidMouse/actions")

    except RuntimeError as e:
        print(f"\n❌ Errore git: {e}")
        print("\n📋 Puoi completare manualmente con:")
        print(f'   git add -u')
        print(f'   git commit -m "{commit_msg}"')
        print(f'   git tag {tag}')
        print(f'   git push {REMOTE} {BRANCH} && git push {REMOTE} {tag}')
        sys.exit(1)


if __name__ == "__main__":
    main()
    if sys.stdin.isatty():
        input("\nPremere Invio per uscire...")
