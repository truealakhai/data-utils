"""
stock_check_main.py — Entry point reale per il controllo stock (GitHub
Actions separato, più frequente dello scan giornaliero principale — vedi
.github/workflows/stock_check.yml). Girare ogni 15-30 minuti l'intero
main.py con tutti gli 8+ scanner sarebbe sprecato; questo file controlla
SOLO stock_watchlist.py, molto più leggero.

Il controllo eBay (STOCK_WATCHLIST -> EBAY_WATCHLIST) è stato spostato in
ebay_check_main.py, su un job orario separato (ebay_check.yml) — troppi
post arrivavano con eBay controllato ogni 20 minuti come i rivenditori
diretti. Per un preordine su un rivenditore un ritardo di 20 minuti può
voler dire "esaurito nel frattempo"; per eBay, dove la domanda è "qual è
il prezzo migliore adesso", un'ora di ritardo non cambia la sostanza.
"""

from __future__ import annotations

import os
import sys

from state_store import StateStore
from telegram_alerts import make_telegram_sender
from stock_monitor import run_stock_check, default_http_get
from stock_watchlist import STOCK_WATCHLIST


def main() -> int:
    required = ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]
    missing = [v for v in required if not os.environ.get(v)]
    if missing:
        print(f"ERRORE: variabili d'ambiente mancanti: {missing}")
        return 1

    store = StateStore("stock_state.json")
    send = make_telegram_sender(os.environ["TELEGRAM_BOT_TOKEN"])
    clients = {"http_get": default_http_get}

    print(f"Controllo stock su {len(STOCK_WATCHLIST)} prodotti (rivenditori diretti)...")
    results = run_stock_check(STOCK_WATCHLIST, store, clients, send, os.environ["TELEGRAM_CHAT_ID"])
    for key, outcome in results.items():
        print(f"  {key}: {outcome}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
