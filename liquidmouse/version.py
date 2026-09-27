"""Versione del progetto — unica fonte di verità.

Questo file è letto anche fuori da Python (regex, senza importarlo):
  - .github/workflows/build.yml  → nome EXE, artifact e release
  - build.py                     → nome della candidate --pre
  - test_server.py               → smoke test
Non aggiungere logica qui: deve restare parsabile con una regex banale.
"""

VERSION = "2.6.0"
CODENAME = "Cyber"    # 2.6.0: tema cyber di PiDash, ritorno al nome Liquid Mouse
