# Familieoppgaver

Oppgavetavle for barna med dagens kalender. Python (kun standardbibliotek), data som JSON i `/data`.

- `/` – tavla (tre kolonner + felles / bare i dag + dagens kalender)
- `/admin` – endre oppgaver
- `POST /api/calendar` – kalenderhendelser pushes hit fra Macen (header `X-Sync-Token`)

Kjør lokalt: `DATA_DIR=./data SYNC_TOKEN=test python3 server.py`
