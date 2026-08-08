"""Whitelist dei comandi del terminale: è un confine di sicurezza."""

import pytest

from liquidmouse.terminal.commands import TERM_ALLOWED_CMDS, resolve_argv


def _which(mapping):
    return lambda cmd: mapping.get(cmd)


class TestWhitelist:
    @pytest.mark.parametrize("cmd", sorted(TERM_ALLOWED_CMDS))
    def test_i_comandi_consentiti_passano(self, cmd):
        argv = resolve_argv(cmd, which=_which({cmd: f"C:\\{cmd}"}),
                            isabs=lambda p: False, exists=lambda p: False)
        assert argv == [f"C:\\{cmd}"]

    @pytest.mark.parametrize("cmd", [
        "format.exe", "rm", "notepad.exe", "python", "curl",
    ])
    def test_i_comandi_non_elencati_sono_rifiutati(self, cmd):
        with pytest.raises(ValueError):
            resolve_argv(cmd, which=_which({}), isabs=lambda p: False,
                         exists=lambda p: False)

    def test_comando_vuoto(self):
        with pytest.raises(ValueError):
            resolve_argv("   ", which=_which({}), isabs=lambda p: False,
                         exists=lambda p: False)

    def test_il_confronto_ignora_le_maiuscole(self):
        argv = resolve_argv("CMD.EXE", which=_which({"CMD.EXE": "C:\\cmd.exe"}),
                            isabs=lambda p: False, exists=lambda p: False)
        assert argv == ["C:\\cmd.exe"]

    def test_gli_argomenti_non_aggirano_la_whitelist(self):
        # Solo il nome base viene confrontato: un comando vietato con argomenti
        # deve restare vietato.
        with pytest.raises(ValueError):
            resolve_argv("del /f /q C:\\", which=_which({}),
                         isabs=lambda p: False, exists=lambda p: False)

    def test_un_argomento_non_promuove_un_comando_vietato(self):
        with pytest.raises(ValueError):
            resolve_argv("evil.exe cmd.exe", which=_which({}),
                         isabs=lambda p: False, exists=lambda p: False)


class TestRisoluzione:
    def test_percorso_assoluto_esistente_usato_com_e(self):
        argv = resolve_argv("bash", which=_which({}),
                            isabs=lambda p: True, exists=lambda p: True)
        assert argv == ["bash"]

    def test_script_batch_passa_dall_interprete(self):
        # CreateProcessW non sa eseguire un .cmd: va passato a cmd.exe /c.
        argv = resolve_argv("claude", which=_which({"claude": "C:\\npm\\claude.cmd"}),
                            isabs=lambda p: False, exists=lambda p: False)
        assert argv == ["cmd.exe", "/c", "C:\\npm\\claude.cmd"]

    def test_script_bat_passa_dall_interprete(self):
        argv = resolve_argv("claude", which=_which({"claude": "C:\\x\\claude.BAT"}),
                            isabs=lambda p: False, exists=lambda p: False)
        assert argv == ["cmd.exe", "/c", "C:\\x\\claude.BAT"]

    def test_comando_non_trovato_resta_tale_e_quale(self):
        # Delega l'errore al backend PTY, che ha il messaggio di sistema.
        argv = resolve_argv("wsl", which=_which({}),
                            isabs=lambda p: False, exists=lambda p: False)
        assert argv == ["wsl"]
