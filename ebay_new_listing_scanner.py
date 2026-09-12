"""
ebay_new_listing_scanner.py — Rileva nuove inserzioni eBay per una query.

Utile per la Rarity Radar: se compaiono inserzioni per un prodotto che prima
non c'erano (es. un premio torneo che nessuno vendeva), è un segnale precoce
di disponibilità — prima ancora che si formi un prezzo storico da tracciare.

Fonte: eBay Browse API (item_summary/search) — VERIFICATA come pubblica ad
accesso self-serve (client credentials grant su developer.ebay.com), NON lo
stesso gate della Marketplace Insights API incontrato prima. Restituisce
solo inserzioni ATTIVE (prezzo di richiesta), mai vendite concluse — quindi
qui produciamo LISTING_CLAIM, mai SOLD_COMP.

Limite noto (segnalato dalla community eBay stessa): per query molto
popolari la paginazione ha un tetto pratico sotto il numero reale di
risultati. Per query di nicchia come le nostre (prodotti TCG specifici) non
dovrebbe pesare, ma se una query restituisce sistematicamente "poco", è il
primo sospetto da controllare.

Classificazione (rivedibile): ogni nuova inserzione = una LISTING_CLAIM (un
singolo venditore, non verificato). Anche se ne compaiono molte da venditori
diversi in poco tempo, per ora restano multiple LISTING_CLAIM — quindi
'Bassa' finché non arriva corroborazione di tipo diverso, stesso principio
già applicato ovunque nel sistema. Da rivedere quando avremo dati reali.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import date
from typing import Callable, List, Optional, Set
from urllib.parse import quote_plus

from scoring import Evidence, SourceType

TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"

HttpPost = Callable[[str, dict, dict], dict]  # (url, headers, form_data) -> JSON
HttpGet = Callable[[str, dict], dict]          # (url, headers) -> JSON


def default_http_post(url: str, headers: dict, data: dict) -> dict:
    import requests
    resp = requests.post(url, headers=headers, data=data, timeout=15)
    resp.raise_for_status()
    return resp.json()


def default_http_get(url: str, headers: dict) -> dict:
    import requests
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    return resp.json()


def get_application_token(
    client_id: str,
    client_secret: str,
    http_post: HttpPost = default_http_post,
) -> str:
    """
    Client credentials grant — token applicativo (no login utente), valido
    circa 2 ore. Cache/rinnovo lasciati al chiamante, per tenere questa
    funzione pura e facilmente testabile.
    """
    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    headers = {
        "Authorization": f"Basic {credentials}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {"grant_type": "client_credentials", "scope": "https://api.ebay.com/oauth/api_scope"}
    resp = http_post(TOKEN_URL, headers, data)
    return resp["access_token"]


@dataclass
class EbayListing:
    item_id: str
    title: str
    url: str
    price: Optional[float]
    currency: str
    seller: str


def search_active_listings(
    query: str,
    access_token: str,
    limit: int = 50,
    marketplace_id: str = "EBAY_IT",  # priorità EU/Italia, come da requisito
    http_get: HttpGet = default_http_get,
) -> List[EbayListing]:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "X-EBAY-C-MARKETPLACE-ID": marketplace_id,
    }
    url = f"{SEARCH_URL}?q={quote_plus(query)}&limit={limit}"
    data = http_get(url, headers)

    listings = []
    for item in data.get("itemSummaries", []):
        price_info = item.get("price", {})
        listings.append(EbayListing(
            item_id=item.get("itemId", ""),
            title=item.get("title", ""),
            url=item.get("itemWebUrl", ""),
            price=float(price_info["value"]) if price_info.get("value") else None,
            currency=price_info.get("currency", ""),
            seller=item.get("seller", {}).get("username", "sconosciuto"),
        ))
    return listings


def find_new_listings(listings: List[EbayListing], seen_item_ids: Set[str]) -> List[EbayListing]:
    """seen_item_ids va gestito dal chiamante — persistenza vera nel punto 'b'."""
    return [l for l in listings if l.item_id not in seen_item_ids]


def listing_to_evidence(listing: EbayListing, observed_on: Optional[date] = None) -> Evidence:
    price_str = f"{listing.price} {listing.currency}" if listing.price else "prezzo n/d"
    return Evidence(
        source_type=SourceType.LISTING_CLAIM,
        source_name=f"eBay - nuova inserzione ({listing.seller})",
        observed_on=observed_on or date.today(),
        url=listing.url,
        note=f"'{listing.title}' — {price_str} — venditore: {listing.seller}",
    )


if __name__ == "__main__":
    def fake_search_response(_query: str) -> List[EbayListing]:
        return [
            EbayListing("111", "Riftbound Chinese Teemo FND 196/298 New Year Promo",
                        "https://ebay.it/itm/111", 890.0, "EUR", "cardshop_it"),
            EbayListing("222", "Riftbound Chinese Teemo FND 196/298 New Year Promo NM",
                        "https://ebay.it/itm/222", 950.0, "EUR", "another_seller_de"),
        ]

    print("=" * 70)
    print("Prima scansione: 2 inserzioni, 0 già viste — tutto 'nuovo' per")
    print("definizione (nella persistenza reale la prima scansione popola lo")
    print("stato senza generare alert, altrimenti ogni prodotto darebbe un")
    print("falso allarme al primo avvio)")
    print("=" * 70)
    listings = fake_search_response("Riftbound Teemo FND 196")
    new = find_new_listings(listings, seen_item_ids=set())
    for l in new:
        ev = listing_to_evidence(l, observed_on=date(2026, 9, 9))
        print(f"  · {ev.note}")

    print()
    print("=" * 70)
    print("Seconda scansione: '111' e '222' già viste, compare '333' da un")
    print("terzo venditore — QUESTO è il segnale reale da alertare")
    print("=" * 70)
    listings2 = fake_search_response("Riftbound Teemo FND 196") + [
        EbayListing("333", "Riftbound Chinese Teemo FND 196/298 PSA 10",
                    "https://ebay.it/itm/333", 1800.0, "EUR", "grading_reseller"),
    ]
    new2 = find_new_listings(listings2, seen_item_ids={"111", "222"})
    for l in new2:
        ev = listing_to_evidence(l, observed_on=date(2026, 9, 9))
        print(f"  · {ev.note}")
