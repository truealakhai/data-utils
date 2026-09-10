# TCG Seeker

Sistema di rilevamento hype/scarsità per prodotti TCG (Pokémon, Yu-Gi-Oh,
Riftbound; WoW TCG resta a verifica manuale, mercato chiuso dal 2013).

## Come funziona

`main.py` gira su GitHub Actions una volta al giorno (`.github/workflows/scan.yml`),
interroga gli scanner per ogni prodotto in `watchlist.py`, salva lo stato in
`state.json` (committato nel repo tra un run e l'altro), e manda un alert
Telegram solo quando un prodotto sale di fascia di affidabilità (Bassa →
Media → Alta) — mai per un semplice giro a vuoto o un calo.

## Setup

1. Crea un nuovo repo GitHub e caricaci tutti questi file.
2. In **Settings → Secrets and variables → Actions**, aggiungi i secrets
   qui sotto. Solo `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID` sono
   obbligatori — gli altri sono opzionali, ma senza abilitano di volta in
   volta meno fonti (main.py te lo segnala nei log, non fallisce in
   silenzio).

| Secret | Dove procurarselo |
|---|---|
| `TELEGRAM_BOT_TOKEN` | @BotFather su Telegram, comando `/newbot` |
| `TELEGRAM_CHAT_ID` | Manda un messaggio al bot, poi leggi il chat_id da `api.telegram.org/bot<TOKEN>/getUpdates` |
| `EBAY_CLIENT_ID` / `EBAY_CLIENT_SECRET` | developer.ebay.com, Browse API (self-serve, non serve approvazione) |
| `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` | reddit.com/prefs/apps — **richiede approvazione manuale** dalla Responsible Builder Policy, fai la richiesta con anticipo |
| `RIFTBOUND_API_KEY` / `TCG_CARDMARKET_API_KEY` | RapidAPI — affidabilità non verificata a fondo, vedi le note in `riftbound_scanner.py` |
| `TCGAPI_DEV_KEY` | tcgapi.dev/dashboard, gratis fino a 100 richieste/giorno |

3. Il workflow è già schedulato alle 8:00 UTC — cambia il cron in `scan.yml`
   se preferisci un altro orario, o lancialo a mano dalla tab **Actions**
   (pulsante "Run workflow", grazie a `workflow_dispatch`).

## Test in locale (prima di fidarti del cron)

```bash
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=...
python main.py
```

## Un limite architetturale da sapere — non ancora risolto

`on_demand_lookup.py` (la ricerca "scrivi il nome di una carta su Telegram")
**non gira su GitHub Actions**. GitHub Actions esegue job schedulati o
lanciati a mano — non sta in ascolto per rispondere a un messaggio Telegram
nell'istante in cui arriva. Serve un processo sempre attivo (polling) o un
endpoint pubblico raggiungibile (webhook), cosa che questo repo da solo non
fornisce.

Opzioni realistiche, da decidere insieme prima di costruirci sopra:
- **Eseguire il polling in locale** sul tuo computer quando vuoi usarlo
  (più semplice, zero costi, ma disponibile solo quando il PC è acceso)
- **Un servizio cloud sempre attivo** (Railway/Fly.io/simili, spesso con un
  tier gratuito limitato) che tiene il bot in polling continuo
- **Un webhook serverless** (es. una function che Telegram chiama
  direttamente) — più efficiente ma più lavoro da configurare

Nessuna delle tre è ancora implementata — `on_demand_lookup.py` così com'è
è pronto per essere richiamato, ma manca il "contenitore" che lo tiene in
ascolto dei messaggi Telegram in tempo reale.

## Struttura del progetto

```
main.py                     # entry point reale (GitHub Actions)
orchestrator.py             # logica di orchestrazione degli scanner
watchlist.py                # prodotti monitorati — modifica QUESTO file
scoring.py                  # scoring/cross-check delle evidenze
state_store.py              # persistenza JSON tra esecuzioni
telegram_alerts.py          # invio alert con deduplica per fascia
on_demand_lookup.py         # ricerca su richiesta (hosting non risolto, vedi sopra)
cardmarket_scanner.py       # Pokémon via tcgdex.dev
yugioh_scanner.py           # Yu-Gi-Oh via YGOPRODeck
riftbound_scanner.py        # Riftbound, 3 fonti commerciali
tcgcsv_scanner.py           # TCGPlayer via tcgcsv.com, multi-gioco
community_scanner.py        # Serebii/PokeBeach
reddit_scanner.py           # Reddit (via PRAW)
ebay_new_listing_scanner.py # nuove inserzioni eBay, universale
.github/workflows/scan.yml  # scheduling
state.json                  # creato/aggiornato automaticamente, non toccarlo a mano
```
