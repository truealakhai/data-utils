"""
orchestrator.py — Lo script che gira davvero (GitHub Actions schedulato,
stesso schema di bot_btc_gold_standard.py). Prende una watchlist ristretta
(mai "tutto il mercato", come deciso in sessione), interroga gli scanner
pertinenti per ogni voce, aggiorna lo stato persistito, e manda alert
Telegram solo sulle salite di fascia.

Due famiglie di scanner, gestite diversamente:
- PER-PRODOTTO (Cardmarket, Yu-Gi-Oh, Riftbound, eBay nuove inserzioni):
  interrogati una volta per ogni voce della watchlist.
- A "SPAZZOLATA" (community/Serebii-PokeBeach, Reddit): interrogati UNA
  volta per l'intero run, poi il risultato viene smistato alle voci della
  watchlist per corrispondenza di parola chiave nel titolo — rifare la
  stessa richiesta per ogni prodotto sarebbe sprecato.

Resilienza: ogni scanner è avvolto in try/except — se UNO fallisce (rete,
formato risposta cambiato, credenziali scadute), il run continua con gli
altri invece di bloccarsi tutto. Motivo pratico, non teorico: con 8 fonti
diverse la probabilità che almeno una fallisca in un dato giorno è alta.
"""

from __future__ import annotations

from datetime import date
from typing import Callable, Dict, List, Optional

from scoring import Evidence
from state_store import StateStore
from telegram_alerts import process_claim, TelegramSend
from watchlist import WATCHLIST  # la watchlist vive nel suo file, non qui



# ---------------------------------------------------------------------------
# Adapter per-prodotto — stessa firma per tutti: (item, clients, store) -> List[Evidence]
# ---------------------------------------------------------------------------

def adapter_cardmarket(item: dict, clients: dict, store: StateStore) -> List[Evidence]:
    from cardmarket_scanner import fetch_card_pricing, snapshot_to_evidence
    snap = fetch_card_pricing(item["cardmarket_id"], http_get=clients["cardmarket_http_get"])
    if snap is None:
        return []
    return [snapshot_to_evidence(snap)]


def adapter_yugioh(item: dict, clients: dict, store: StateStore) -> List[Evidence]:
    from yugioh_scanner import fetch_card_prices, snapshot_to_evidences
    snap = fetch_card_prices(item["query"], http_get=clients["yugioh_http_get"])
    if snap is None:
        return []
    return snapshot_to_evidences(snap)


def adapter_riftbound(item: dict, clients: dict, store: StateStore) -> List[Evidence]:
    from riftbound_scanner import fetch_all_riftbound_sources
    return fetch_all_riftbound_sources(
        item["query"],
        api_keys=item.get("riftbound_api_keys", {}),
        http_get=clients["riftbound_http_get"],
    )


def adapter_ebay_new_listings(item: dict, clients: dict, store: StateStore) -> List[Evidence]:
    from ebay_new_listing_scanner import search_active_listings, find_new_listings, listing_to_evidence
    listings = search_active_listings(
        item["query"], access_token=clients["ebay_token"], http_get=clients["ebay_http_get"],
    )
    seen_key = f"ebay:{item['claim_id']}"
    seen = store.get_seen(seen_key)
    new = find_new_listings(listings, seen)
    store.mark_seen(seen_key, {l.item_id for l in listings})
    return [listing_to_evidence(l) for l in new]


PER_PRODUCT_ADAPTERS: Dict[str, Callable] = {
    "cardmarket": adapter_cardmarket,
    "yugioh": adapter_yugioh,
    "riftbound": adapter_riftbound,
    "ebay_new_listings": adapter_ebay_new_listings,
}


# ---------------------------------------------------------------------------
# Scanner a spazzolata — una volta per run, poi smistati per parola chiave
# ---------------------------------------------------------------------------

def sweep_community(clients: dict, store: StateStore) -> List:
    from community_scanner import serebii_fetch_headlines, pokebeach_fetch_headlines, find_new_relevant_headlines
    headlines = []
    headlines += serebii_fetch_headlines(http_get=clients["serebii_http_get"])
    headlines += pokebeach_fetch_headlines(http_get=clients["pokebeach_http_get"])
    seen = store.get_seen("community")
    new_relevant = find_new_relevant_headlines(headlines, seen, tcg_only=False)  # il match per query filtra dopo
    store.mark_seen("community", {h.url for h in headlines})
    return new_relevant


def sweep_reddit(clients: dict, store: StateStore) -> List:
    from reddit_scanner import scan_subreddits, find_new_relevant_posts
    posts = scan_subreddits(clients["reddit_client"], query="", subreddits=None, limit_per_sub=50)
    seen = store.get_seen("reddit")
    new_relevant = find_new_relevant_posts(posts, seen)
    store.mark_seen("reddit", {p.post_id for p in posts})
    return new_relevant


def match_sweep_to_items(sweep_results: List, watchlist: List[dict], source_key: str) -> Dict[str, List[Evidence]]:
    """Smista i risultati della spazzolata alle voci watchlist il cui 'query'
    compare nel titolo (match semplice, case-insensitive — non serve altro
    per una watchlist piccola)."""
    from community_scanner import headline_to_evidence, Headline
    from reddit_scanner import post_to_evidence, RedditPost

    by_claim: Dict[str, List[Evidence]] = {}
    for item in watchlist:
        if source_key not in item["sources"]:
            continue
        query_lower = item["query"].lower()
        matched = [
            r for r in sweep_results
            if query_lower in (r.title if isinstance(r, (Headline, RedditPost)) else "").lower()
        ]
        evidences = []
        for r in matched:
            if isinstance(r, Headline):
                evidences.append(headline_to_evidence(r))
            elif isinstance(r, RedditPost):
                evidences.append(post_to_evidence(r))
        if evidences:
            by_claim.setdefault(item["claim_id"], []).extend(evidences)
    return by_claim


# ---------------------------------------------------------------------------
# Runner principale
# ---------------------------------------------------------------------------

def run_scan(
    watchlist: List[dict],
    store: StateStore,
    clients: dict,
    send: TelegramSend,
    chat_id: str,
    as_of: Optional[date] = None,
) -> Dict[str, str]:
    """Ritorna {claim_id: esito} per log/debug — 'nessun alert' o la fascia raggiunta."""
    results: Dict[str, str] = {}
    evidence_by_claim: Dict[str, List[Evidence]] = {}

    # --- fase 1: scanner per-prodotto ---
    for item in watchlist:
        claim_id = item["claim_id"]
        evidence_by_claim.setdefault(claim_id, [])
        for source_name in item["sources"]:
            adapter = PER_PRODUCT_ADAPTERS.get(source_name)
            if adapter is None:
                continue  # community/reddit gestiti nella fase 2
            try:
                evidence_by_claim[claim_id] += adapter(item, clients, store)
            except Exception as e:
                print(f"  [ERRORE] {source_name} su {claim_id}: {e} — continuo con le altre fonti")

    # --- fase 2: scanner a spazzolata ---
    try:
        community_results = sweep_community(clients, store)
        for claim_id, evs in match_sweep_to_items(community_results, watchlist, "community").items():
            evidence_by_claim[claim_id] += evs
    except Exception as e:
        print(f"  [ERRORE] sweep community: {e} — continuo senza")

    try:
        reddit_results = sweep_reddit(clients, store)
        for claim_id, evs in match_sweep_to_items(reddit_results, watchlist, "reddit").items():
            evidence_by_claim[claim_id] += evs
    except Exception as e:
        print(f"  [ERRORE] sweep reddit: {e} — continuo senza")

    # --- fase 3: scoring + alert per ogni claim ---
    for claim_id, new_evidence in evidence_by_claim.items():
        try:
            score = process_claim(claim_id, new_evidence, store, send, chat_id, as_of=as_of)
            results[claim_id] = f"ALERT -> {score.band}" if score else "nessun alert"
        except Exception as e:
            results[claim_id] = f"ERRORE: {e}"
            print(f"  [ERRORE] scoring/alert su {claim_id}: {e}")

    return results


if __name__ == "__main__":
    import os
    import tempfile
    from datetime import date, datetime, timezone

    from community_scanner import Headline
    from reddit_scanner import RedditPost

    # --- Ambiente finto: un router HTTP per ciascuno scanner, coerente con ---
    # --- i dati reali già verificati altrove in questo progetto ---

    def fake_cardmarket_http(url: str) -> dict:
        return {
            "name": "Grookey (esempio con hype)",
            "pricing": {"cardmarket": {
                "updated": "2026-09-09T00:00:00.000Z", "unit": "EUR",
                "avg": 12.0, "low": 9.0, "trend": 22.0, "avg30": 12.0,
            }},
        }

    def fake_yugioh_http(url: str) -> dict:
        return {"data": [{
            "id": 89631139, "name": "Blue-Eyes White Dragon",
            "card_prices": [{"cardmarket_price": "3.50", "tcgplayer_price": "4.10",
                              "ebay_price": "5.99", "amazon_price": "0", "coolstuffinc_price": "3.99"}],
            "card_sets": [{"set_rarity": "Ultra Rare"}],
        }]}

    def fake_riftbound_http(url: str, headers: dict) -> dict:
        if "riftbound-api" in url:
            return {"id": 1, "name": "Jinx",
                     "prices": {"cardmarket": {"trend": 12.45, "avg_30d": 10.52},
                                "tcgplayer": {"market": 13.2}},
                     "last_updated": "2026-09-09T00:00:00Z"}
        if "tcg-cardmarket-api" in url:
            return {"data": [{"name": "Jinx", "price": {"trend": 12.45, "avg7": 11.89, "avg30": 10.52, "low": 9.99}}]}
        return {}

    def fake_ebay_http(url: str, headers: dict) -> dict:
        if "Teemo" in url:
            return {"itemSummaries": [{
                "itemId": "111", "title": "Riftbound Teemo FND 196 New Year Promo",
                "itemWebUrl": "https://ebay.it/111",
                "price": {"value": "900", "currency": "EUR"},
                "seller": {"username": "new_seller_it"},
            }]}
        return {"itemSummaries": []}

    def fake_serebii_http(url: str) -> str:
        return """<html><body>
        <h2>Wednesday update</h2>
        <h3>In The TCG Department</h3>
        <a href="https://serebii.net/news/grookey-exclusive">Grookey gets exclusive limited promo, sold out in minutes</a>
        <h3>In The Games Department</h3>
        <a href="https://serebii.net/news/other">Ranked Battle season announced</a>
        </body></html>"""

    def fake_pokebeach_http(url: str) -> str:
        return '<html><body><h2><a href="https://pokebeach.com/news/1">Restock alert for a random product</a></h2></body></html>'

    class FakeRedditClient:
        def search_subreddit(self, subreddit: str, query: str, limit: int):
            now = datetime(2026, 9, 9, tzinfo=timezone.utc).timestamp()
            if subreddit == "PokemonTCG":
                return [RedditPost("g1", "Grookey exclusive promo confirmed, limited print run",
                                    "https://reddit.com/g1", subreddit, now, 220, 45)]
            if subreddit == "yugioh":
                return [RedditPost("b1", "Blue-Eyes White Dragon tournament exclusive prize announced",
                                    "https://reddit.com/b1", subreddit, now, 180, 30)]
            return []

    clients = {
        "cardmarket_http_get": fake_cardmarket_http,
        "yugioh_http_get": fake_yugioh_http,
        "riftbound_http_get": fake_riftbound_http,
        "ebay_token": "FAKE_TOKEN",
        "ebay_http_get": fake_ebay_http,
        "serebii_http_get": fake_serebii_http,
        "pokebeach_http_get": fake_pokebeach_http,
        "reddit_client": FakeRedditClient(),
    }

    tmp_path = os.path.join(tempfile.gettempdir(), "tcg_seeker_orchestrator_demo.json")
    if os.path.exists(tmp_path):
        os.remove(tmp_path)
    store = StateStore(tmp_path)

    sent_messages = []
    def fake_send(chat_id: str, text: str) -> None:
        sent_messages.append((chat_id, text))

    print("=" * 70)
    print("RUN 1 — prima esecuzione dell'orchestratore su tutta la watchlist")
    print("=" * 70)
    results1 = run_scan(WATCHLIST, store, clients, fake_send, chat_id="12345", as_of=date(2026, 9, 9))
    for claim_id, outcome in results1.items():
        print(f"  {claim_id}: {outcome}")
    print(f"\n  messaggi Telegram inviati: {len(sent_messages)}")
    for chat, text in sent_messages:
        print("\n  --- alert ---")
        print("  " + text.replace("\n", "\n  "))

    print()
    print("=" * 70)
    print("RUN 2 — stesso run ripetuto (simula il giorno dopo, stessi dati):")
    print("niente deve duplicarsi né rialertare")
    print("=" * 70)
    store2 = StateStore(tmp_path)
    results2 = run_scan(WATCHLIST, store2, clients, fake_send, chat_id="12345", as_of=date(2026, 9, 9))
    for claim_id, outcome in results2.items():
        print(f"  {claim_id}: {outcome}")
    print(f"\n  messaggi Telegram inviati in totale (invariato = corretto): {len(sent_messages)}")
