"""
stock_check_main.py — Entry point reale per il controllo stock (GitHub
Actions separato, più frequente dello scan giornaliero principale — vedi
.github/workflows/stock_check.yml). Girare ogni 15-30 minuti l'intero
main.py con tutti gli 8+ scanner sarebbe sprecato; questo file controlla
SOLO stock_watchlist.py, molto più leggero.
"""

from __future__ import annotations

import os
import sys

from state_store import StateStore
from telegram_alerts import make_telegram_sender
from stock_monitor import run_stock_check, run_ebay_check, default_http_get
from stock_watchlist import STOCK_WATCHLIST, EBAY_WATCHLIST
from ebay_new_listing_scanner import get_application_token


def build_ebay_token():
    if not os.environ.get("EBAY_CLIENT_ID") or not os.environ.get("EBAY_CLIENT_SECRET"):
        print("  [info] Credenziali eBay assenti — controllo eBay disattivato")
        return None
    try:
        return get_application_token(os.environ["EBAY_CLIENT_ID"], os.environ["EBAY_CLIENT_SECRET"])
    except Exception as e:
        print(f"  [ERRORE] Autenticazione eBay fallita ({e}) — controllo eBay disattivato")
        return None


def main() -> int:
    required = ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]
    missing = [v for v in required if not os.environ.get(v)]
    if missing:
        print(f"ERRORE: variabili d'ambiente mancanti: {missing}")
        return 1

    store = StateStore("stock_state.json")  # file separato da state.json dello scan principale
    send = make_telegram_sender(os.environ["TELEGRAM_BOT_TOKEN"])
    clients = {"http_get": default_http_get}

    print(f"Controllo stock su {len(STOCK_WATCHLIST)} prodotti (rivenditori diretti)...")
    results = run_stock_check(STOCK_WATCHLIST, store, clients, send, os.environ["TELEGRAM_CHAT_ID"])
    for key, outcome in results.items():
        print(f"  {key}: {outcome}")

    print(f"Controllo eBay su {len(EBAY_WATCHLIST)} prodotti...")
    ebay_token = build_ebay_token()
    ebay_results = run_ebay_check(EBAY_WATCHLIST, store, ebay_token, send, os.environ["TELEGRAM_CHAT_ID"])
    for key, outcome in ebay_results.items():
        print(f"  {key}: {outcome}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
