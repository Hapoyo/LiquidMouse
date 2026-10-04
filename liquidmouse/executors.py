"""Executor dedicati ai lavori bloccanti dell'event loop.

Prima tutto passava da `run_in_executor(None, ...)`: un solo pool condiviso, in
cui le read dei PTY (che restano bloccate finché la shell non scrive) potevano
occupare ogni thread e far aspettare un listing SFTP o la discovery UPnP. Ogni
categoria ha ora il suo pool, così nessuna ne affama un'altra.
"""

from concurrent.futures import ThreadPoolExecutor

# Una read bloccata tiene un thread per tutta la vita della sessione: servono
# almeno tanti thread quante sessioni (MAX_SESSIONS in terminal/sessions.py,
# controllato da test_sessions) più un po' di margine per il backend ConPTY.
PTY_READ_WORKERS = 12
# Una write può bloccare se la shell non legge e la pipe è piena: un thread
# per sessione, e comunque separato da quelli di lettura.
PTY_WRITE_WORKERS = 8

PTY_READ = ThreadPoolExecutor(PTY_READ_WORKERS, thread_name_prefix="lm-pty-read")
PTY_WRITE = ThreadPoolExecutor(PTY_WRITE_WORKERS, thread_name_prefix="lm-pty-write")
SFTP = ThreadPoolExecutor(6, thread_name_prefix="lm-sftp")
# Discovery e mapping UPnP, pulizia alla chiusura: lavori rari e lenti (fino a 2 s).
NET = ThreadPoolExecutor(2, thread_name_prefix="lm-net")
