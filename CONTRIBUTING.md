# Contribuire a LiquidMouse

Bug, idee o miglioramenti sono benvenuti. Apri un issue o una pull request.

## Segnalare un bug

Prima di aprire un issue, verifica che non sia già stato segnalato.

Includi:
- Comportamento atteso e comportamento osservato
- Passi per riprodurlo
- OS, versione Python, browser usato

## Proporre una funzionalità

Apri un issue descrivendo cosa vuoi aggiungere e perché è utile.

## Pull request

1. Fai un fork del repository
2. Crea un branch (`git checkout -b feature/nome`)
3. Committa le modifiche
4. Apri una pull request verso `main`

Mantieni le modifiche focalizzate — una PR per problema.

## Sviluppo

Struttura del codice e convenzioni: vedi [CLAUDE.md](CLAUDE.md).

```bash
pip install pytest
python -m pytest              # test unitari — girano anche fuori da Windows
python build.py               # genera l'EXE in EXE/
py -3.13 test_server.py       # smoke test, con il server gia' avviato
```

I test unitari partono su ogni push e PR. Se tocchi il protocollo dei messaggi o
il serving degli asset, aggiungi il caso corrispondente in `tests/` — sono le due
aree dove un errore si manifesta solo da remoto o solo dentro l'EXE.

Prima di aprire una PR che tocca build, asset statici o protocollo, prova
**l'EXE prodotto** e il **percorso remoto sulla porta 8443**, non solo il
sorgente in LAN.

## Licenza

Contribuendo accetti che il tuo codice venga distribuito sotto licenza GPL v3.
