"""Whitelist dei comandi avviabili in una sessione terminale.

È un confine di sicurezza: chiunque raggiunga il WebSocket autenticato può
chiedere di eseguire un comando, quindi qui passa solo ciò che è esplicitamente
elencato. La whitelist si applica al nome base, non alla riga completa.
"""

import os
import shutil

# (comando, etichetta mostrata dal client) nell'ordine in cui si offrono. È l'unica
# fonte: la whitelist deriva da qui, quindi ciò che il client può scegliere e ciò
# che il server accetta non possono divergere.
SHELLS = (
    ("cmd.exe", "cmd"),
    ("powershell.exe", "powershell"),
    ("pwsh.exe", "pwsh"),
    ("wsl", "wsl"),
    ("bash", "bash"),
    ("claude", "claude"),
)
TERM_ALLOWED_CMDS = {cmd for cmd, _ in SHELLS}


def available_shells(which=shutil.which) -> list[dict]:
    """Shell da offrire al client: quelle in whitelist realmente installate.

    cmd.exe c'è sempre su Windows. Per le altre si guarda il PATH, così il
    telefono non propone un pulsante che finirebbe in "Errore PTY". La whitelist
    resta l'autorità: `resolve_argv` ricontrolla comunque ogni richiesta.
    """
    return [{"cmd": cmd, "label": label} for cmd, label in SHELLS
            if cmd == "cmd.exe" or which(cmd)]


def resolve_argv(cmd: str, which=shutil.which, isabs=os.path.isabs, exists=os.path.exists) -> list:
    """Traduce il comando richiesto dal client in un argv eseguibile.

    Solleva ValueError se il comando non è in whitelist. Le funzioni di
    filesystem sono iniettabili per poter testare la logica fuori da Windows.
    """
    parts = cmd.strip().split()
    if not parts:
        raise ValueError("Comando vuoto")
    base = parts[0].lower()
    if base not in TERM_ALLOWED_CMDS:
        raise ValueError(f"Comando non consentito: {cmd!r}")
    if isabs(cmd) and exists(cmd):
        return [cmd]
    exe = which(cmd)
    # Un .cmd/.bat non è un eseguibile: CreateProcessW lo rifiuterebbe, va
    # passato all'interprete.
    if exe and exe.lower().endswith(('.cmd', '.bat')):
        return ["cmd.exe", "/c", exe]
    return [exe] if exe else [cmd]
