"""
yugioh_scanner.py — Scanner prezzi Yu-Gi-Oh via YGOPRODeck (API v7).

Fonte: https://db.ygoprodeck.com/api/v7/cardinfo.php — gratuita, senza
autenticazione, rate limit 20 richieste/secondo per IP (generoso). Community-run,
ma è la fonte open-data canonica dell'ecosistema Yu-Gi-Oh! (usata da deck-builder,
bot Discord, ecc. — non un prodotto commerciale nuovo senza track record, a
differenza di alcune opzioni Riftbound che vedremo dopo).

DUE AVVERTENZE DALLA DOCUMENTAZIONE UFFICIALE, da rispettare nel design:

1) card_prices riporta "il prezzo più basso trovato tra le versioni multiple
   di quella carta" — se una carta ha più stampe/rarità, il prezzo potrebbe
   NON corrispondere alla stampa specifica che ti interessa. Il campo
   card_sets (rarità/edizione per set) andrebbe incrociato quando serve
   precisione sulla singola stampa — non lo risolvo qui, lo segnalo soltanto.

2) Non è documentato se cardmarket_price/tcgplayer_price/ebay_price siano un
   "trend", una media o altro — a differenza di tcgdex (che dichiara
   esplicitamente cosa sono avg30/trend). Per questo TUTTI i campi di questa
   fonte finiscono in AGGREGATE_STAT, MAI in SOLD_COMP — "ebay_price" incluso,
   anche se il nome potrebbe suggerire una vendita reale: non lo è documentato
   come tale, quindi non lo trattiamo come tale.

Client HTTP iniettabile, stesso schema degli altri scanner (niente rete in
questo ambiente: qui testiamo con risposte finte).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Callable, List, Optional

from scoring import Evidence, SourceType

YGOPRODECK_CARDINFO_URL = "https://db.ygoprodeck.com/api/v7/cardinfo.php"

HttpGet = Callable[[str], dict]  # url (già con querystring) -> JSON parsato


def default_http_get(url: str) -> dict:
    """Implementazione reale per l'uso in produzione. Non eseguibile qui (niente rete)."""
    import requests
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    return resp.json()


# Nomi dei campi prezzo nel JSON YGOPRODeck -> etichetta marketplace da usare in Evidence
PRICE_FIELDS = {
    "cardmarket_price": "Cardmarket",
    "tcgplayer_price": "TCGPlayer",
    "ebay_price": "eBay",
    "amazon_price": "Amazon",
    "coolstuffinc_price": "CoolStuffInc",
}


@dataclass
class YugiohPriceSnapshot:
    card_id: int
    card_name: str
    prices: dict  # marketplace_label -> float (solo quelli > 0 / non nulli)
    set_rarities: List[str] = field(default_factory=list)  # dalle card_sets, per il caveat #1


def fetch_card_prices(
    name: str,
    http_get: HttpGet = default_http_get,
    fuzzy: bool = False,
) -> Optional[YugiohPriceSnapshot]:
    """
    Cerca una carta per nome esatto (o fuzzy con fuzzy=True, usa 'fname') e
    restituisce lo snapshot prezzi. None se non trovata.
    """
    param = "fname" if fuzzy else "name"
    url = f"{YGOPRODECK_CARDINFO_URL}?{param}={name}"
    data = http_get(url)

    if "error" in data:
        return None

    cards = data.get("data", [])
    if not cards:
        return None

    card = cards[0]  # primo risultato; con fname potrebbero essercene altri
    raw_prices = (card.get("card_prices") or [{}])[0]

    prices = {}
    for field_name, label in PRICE_FIELDS.items():
        raw_val = raw_prices.get(field_name)
        try:
            val = float(raw_val)
        except (TypeError, ValueError):
            continue
        if val > 0:
            prices[label] = val

    rarities = sorted({
        s.get("set_rarity", "") for s in card.get("card_sets", []) if s.get("set_rarity")
    })

    return YugiohPriceSnapshot(
        card_id=card.get("id"),
        card_name=card.get("name", name),
        prices=prices,
        set_rarities=rarities,
    )


def snapshot_to_evidences(snap: YugiohPriceSnapshot, as_of: Optional[date] = None) -> List[Evidence]:
    """
    Una Evidence AGGREGATE_STAT per ogni marketplace con prezzo disponibile.
    Data di osservazione: YGOPRODeck non restituisce un timestamp di aggiornamento
    per-prezzo nella risposta cardinfo, quindi uso 'as_of' (oggi se non passato) —
    e lo segnalo nella nota, per onestà sul fatto che non è la data reale del dato
    ma la data in cui l'abbiamo interrogato.
    """
    as_of = as_of or date.today()
    rarity_note = (
        f" [ATTENZIONE: carta con {len(snap.set_rarities)} rarità/edizioni diverse "
        f"({', '.join(snap.set_rarities)}) — il prezzo potrebbe riferirsi alla stampa "
        f"più economica, non a quella che ti interessa]"
        if len(snap.set_rarities) > 1 else ""
    )
    evidences = []
    for marketplace, price in snap.prices.items():
        evidences.append(Evidence(
            source_type=SourceType.AGGREGATE_STAT,
            source_name=f"YGOPRODeck - prezzo {marketplace}",
            observed_on=as_of,
            url=f"{YGOPRODECK_CARDINFO_URL}?id={snap.card_id}",
            note=f"{marketplace}: {price} (metodologia non documentata da YGOPRODeck){rarity_note}",
            marketplace=marketplace,
        ))
    return evidences


if __name__ == "__main__":
    def fake_http_get(url: str) -> dict:
        if "Blue-Eyes" in url:
            return {
                "data": [{
                    "id": 89631139,
                    "name": "Blue-Eyes White Dragon",
                    "card_prices": [{
                        "cardmarket_price": "3.50",
                        "tcgplayer_price": "4.10",
                        "ebay_price": "5.99",
                        "amazon_price": "0.00",
                        "coolstuffinc_price": "3.99",
                    }],
                    "card_sets": [
                        {"set_rarity": "Ultra Rare"},
                        {"set_rarity": "Common"},
                        {"set_rarity": "Starlight Rare"},
                    ],
                }]
            }
        return {"error": "No card matching your query was found in the database."}

    print("=" * 70)
    print("Blue-Eyes White Dragon — nota il caveat sulle rarità multiple:")
    print("il prezzo È quello della stampa più economica (Common), non della")
    print("Starlight Rare che magari interessa a noi")
    print("=" * 70)
    snap = fetch_card_prices("Blue-Eyes White Dragon", http_get=fake_http_get)
    for ev in snapshot_to_evidences(snap, as_of=date(2026, 9, 9)):
        print(f"  · {ev.marketplace:12s} {ev.note}")

    print()
    print("=" * 70)
    print("Carta non trovata")
    print("=" * 70)
    missing = fetch_card_prices("Carta Inesistente XYZ", http_get=fake_http_get)
    print(f"  risultato: {missing}")
