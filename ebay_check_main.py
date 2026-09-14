"""
ebay_check_main.py — Entry point reale per il controllo eBay (GitHub
Actions separato, orario — vedi .github/workflows/ebay_check.yml).

Prima faceva parte di stock_check_main.py, sullo stesso ciclo da 20 minuti
dei rivenditori diretti — troppi post. eBay risponde alla domanda "qual è
il prezzo migliore adesso", non "è appena diventato disponibile": un ritardo
di un'ora non cambia la sostanza, a differenza di un preordine diretto che
può esaurirsi in pochi minuti. File di stato separato (ebay_state.json) da
stock_state.json, stessa ragione per cui i due controlli non condividono
già un file con lo scan giornaliero: workflow diversi che committano lo
stesso file possono andare in conflitto se girano vicini nel tempo.
"""

from __future__ import annotations

import os
import sys

from state_store import StateStore
from telegram_alerts import make_telegram_sender
from stock_monitor import run_ebay_check
from stock_watchlist import EBAY_WATCHLIST
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

    store = StateStore("ebay_state.json")  # file separato da stock_state.json e da state.json
    send = make_telegram_sender(os.environ["TELEGRAM_BOT_TOKEN"])

    print(f"Controllo eBay su {len(EBAY_WATCHLIST)} prodotti...")
    ebay_token = build_ebay_token()
    results = run_ebay_check(EBAY_WATCHLIST, store, ebay_token, send, os.environ["TELEGRAM_CHAT_ID"])
    for key, outcome in results.items():
        print(f"  {key}: {outcome}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
