"""Whitelist dei comandi avviabili in una sessione terminale.

È un confine di sicurezza: chiunque raggiunga il WebSocket autenticato può
chiedere di eseguire un comando, quindi qui passa solo ciò che è esplicitamente
elencato. La whitelist si applica al nome base, non alla riga completa.
"""

import os
import shutil

TERM_ALLOWED_CMDS = {"cmd.exe", "powershell.exe", "pwsh.exe", "claude", "bash", "wsl"}


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
