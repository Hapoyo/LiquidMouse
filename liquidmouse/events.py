"""Log applicativo disaccoppiato dalla GUI.

Prima di questo modulo `log_message` era definita in fondo a server.pyw e
scriveva direttamente sui widget Tk, pur essendo chiamata dal codice di rete,
dal terminale e dalla config: qualunque modulo estratto si sarebbe portato
dietro tkinter (e sarebbe stato non importabile senza una finestra aperta).

Qui il core pubblica e basta. La GUI si registra con `subscribe()` all'avvio;
se nessuno è registrato i messaggi cadono nel vuoto senza errori, che è
esattamente quello che serve ai test e a un eventuale avvio headless.
"""

from collections.abc import Callable

# Firma di un sink: (message: str, color: str | None) -> None
Sink = Callable[[str, "str | None"], None]

_sinks: list[Sink] = []


def subscribe(sink: Sink) -> None:
    """Registra un consumatore di log (tipicamente la GUI Tk)."""
    if sink not in _sinks:
        _sinks.append(sink)


def unsubscribe(sink: Sink) -> None:
    """Rimuove un consumatore già registrato. No-op se non presente."""
    try:
        _sinks.remove(sink)
    except ValueError:
        pass


def log_message(message: str, color: str | None = None) -> None:
    """Pubblica un messaggio di log verso tutti i sink registrati.

    Un sink che solleva non deve impedire agli altri di ricevere il messaggio,
    né far fallire il chiamante: questa funzione è invocata anche da rami di
    gestione errori e da `finally`, dove un'eccezione maschererebbe il problema
    originale.
    """
    for sink in list(_sinks):
        try:
            sink(message, color)
        except Exception:
            pass
