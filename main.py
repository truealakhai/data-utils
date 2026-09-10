"""
main.py — Entry point REALE, quello che gira su GitHub Actions (non i demo
con client finti negli altri file). Costruisce i client HTTP veri da
variabili d'ambiente/secrets, e lancia orchestrator.run_scan.

Variabili d'ambiente richieste/opzionali — vedi README.md per i dettagli su
dove procurarsele:
- TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (richieste)
- EBAY_CLIENT_ID, EBAY_CLIENT_SECRET (opzionali: senza, niente scanner eBay)
- REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET (opzionali: senza, niente scanner Reddit —
  ricorda l'approvazione manuale di Reddit di cui abbiamo parlato)
- RIFTBOUND_API_KEY, TCG_CARDMARKET_API_KEY, TCGAPI_DEV_KEY (opzionali,
  ciascuna abilita una delle fonti Riftbound — puoi averne anche solo una)
"""

from __future__ import annotations

import os
import sys

from state_store import StateStore
from telegram_alerts import make_telegram_sender
from orchestrator import run_scan
from watchlist import WATCHLIST

from cardmarket_scanner import default_http_get as cardmarket_http_get
from yugioh_scanner import default_http_get as yugioh_http_get
from riftbound_scanner import default_http_get as riftbound_http_get
from community_scanner import default_http_get as community_http_get
from ebay_new_listing_scanner import default_http_get as ebay_http_get, get_application_token


class _NullRedditClient:
    """Usato quando mancano le credenziali Reddit — lo scanner Reddit
    restituisce sempre lista vuota invece di far fallire tutto il run."""
    def search_subreddit(self, subreddit: str, query: str, limit: int):
        return []


def build_reddit_client():
    if not os.environ.get("REDDIT_CLIENT_ID") or not os.environ.get("REDDIT_CLIENT_SECRET"):
        print("  [info] Credenziali Reddit assenti — scanner Reddit disattivato per questo run")
        return _NullRedditClient()

    import praw
    from reddit_scanner import RedditPost

    reddit = praw.Reddit(
        client_id=os.environ["REDDIT_CLIENT_ID"],
        client_secret=os.environ["REDDIT_CLIENT_SECRET"],
        user_agent="tcg-seeker/1.0 (by u/your_username)",  # personalizza con il tuo username Reddit
    )

    class PrawRedditClient:
        def search_subreddit(self, subreddit: str, query: str, limit: int):
            sub = reddit.subreddit(subreddit)
            listing = sub.search(query, limit=limit) if query else sub.new(limit=limit)
            posts = []
            for p in listing:
                posts.append(RedditPost(
                    post_id=p.id,
                    title=p.title,
                    url=f"https://reddit.com{p.permalink}",
                    subreddit=subreddit,
                    created_utc=p.created_utc,
                    score=p.score,
                    num_comments=p.num_comments,
                ))
            return posts

    return PrawRedditClient()


def build_ebay_token():
    if not os.environ.get("EBAY_CLIENT_ID") or not os.environ.get("EBAY_CLIENT_SECRET"):
        print("  [info] Credenziali eBay assenti — scanner eBay disattivato per questo run")
        return None
    try:
        return get_application_token(os.environ["EBAY_CLIENT_ID"], os.environ["EBAY_CLIENT_SECRET"])
    except Exception as e:
        print(f"  [ERRORE] Autenticazione eBay fallita ({e}) — scanner eBay disattivato per questo run, continuo con le altre fonti")
        return None


def populate_riftbound_keys(watchlist: list) -> None:
    """Inserisce le chiavi Riftbound lette da env nelle voci watchlist che
    ne hanno bisogno — invece di scriverle a mano in watchlist.py."""
    keys = {
        "riftbound_api": os.environ.get("RIFTBOUND_API_KEY"),
        "tcg_cardmarket_api": os.environ.get("TCG_CARDMARKET_API_KEY"),
        "tcgapi_dev": os.environ.get("TCGAPI_DEV_KEY"),
    }
    active_keys = {k: v for k, v in keys.items() if v}
    if not active_keys:
        print("  [info] Nessuna chiave Riftbound presente — quelle fonti saranno saltate per le voci Riftbound")
    for item in watchlist:
        if item.get("game") == "riftbound":
            item["riftbound_api_keys"] = active_keys


def main() -> int:
    required = ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]
    missing = [v for v in required if not os.environ.get(v)]
    if missing:
        print(f"ERRORE: variabili d'ambiente mancanti: {missing} — controlla i secrets del repo")
        return 1

    populate_riftbound_keys(WATCHLIST)

    clients = {
        "cardmarket_http_get": cardmarket_http_get,
        "yugioh_http_get": yugioh_http_get,
        "riftbound_http_get": riftbound_http_get,
        "ebay_token": build_ebay_token(),
        "ebay_http_get": ebay_http_get,
        "serebii_http_get": community_http_get,
        "pokebeach_http_get": community_http_get,
        "reddit_client": build_reddit_client(),
    }

    store = StateStore("state.json")  # nella root del repo, committato da GitHub Actions dopo il run
    send = make_telegram_sender(os.environ["TELEGRAM_BOT_TOKEN"])

    print("Avvio scan...")
    results = run_scan(WATCHLIST, store, clients, send, chat_id=os.environ["TELEGRAM_CHAT_ID"])

    print("\nRisultati:")
    for claim_id, outcome in results.items():
        print(f"  {claim_id}: {outcome}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
