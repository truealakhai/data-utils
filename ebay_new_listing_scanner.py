"""
ebay_new_listing_scanner.py — Rileva nuove inserzioni eBay per una query,
segnala sempre le inserzioni col prezzo totale (prodotto + spedizione) più
basso, e supporta ricerche multi-keyword con filtro anti-falsi-positivi.

Utile per la Rarity Radar: se compaiono inserzioni per un prodotto che prima
non c'erano (es. un premio torneo che nessuno vendeva), è un segnale precoce
di disponibilità — prima ancora che si formi un prezzo storico da tracciare.
In aggiunta, indipendentemente dalla "novità", vogliamo sempre sapere qual è
il miglior prezzo attuale disponibile per decidere se comprare.

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

Note di design aggiunte in questa versione:

1) PREZZO PIÙ BASSO A PRESCINDERE DA TUTTO — select_cheapest() ignora
   completamente seen_item_ids: anche un'inserzione già segnalata prima va
   comunque riproposta se resta tra le più economiche. È un segnale diverso
   da "cosa è cambiato", è "qual è il migliore adesso".

2) SPEDIZIONE SCONOSCIUTA → MAI TRATTATA COME GRATUITA — se l'API non
   riporta un costo di spedizione, total_price torna None e l'inserzione è
   esclusa dal confronto sul prezzo più basso. Assumere 0€ per un dato
   mancante falserebbe esattamente il confronto che l'utente ha chiesto di
   rendere affidabile. Nota per il futuro: per le inserzioni "quasi vincenti"
   ma con spedizione ignota, si potrebbe fare una chiamata aggiuntiva
   all'endpoint getItem (dettaglio) solo per quelle poche candidate, invece
   che scartarle — non implementato qui per non aggiungere altre chiamate
   API silenziose; da valutare se il caso si presenta spesso.

3) MULTI-KEYWORD CON FILTRO ANTI-FALSI-POSITIVI — search_active_listings_multi
   lancia una query per ogni variante (nomi IT/EN, abbreviazioni) e unisce i
   risultati deduplicando per item_id. filter_relevant_listings applica poi
   la logica "in caso di dubbio, scarta": un solo termine di esclusione
   trovato nel titolo basta a buttar via l'inserzione, a prescindere da
   quanti segnali positivi ci siano altrove nel titolo. Pensato per essere
   alimentato dalle liste già definite in keywords.py (GENERIC/POKEMON/
   YUGIOH/RIFTBOUND/EXCLUDE) invece di duplicare le parole chiave qui.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import date
from typing import Callable, Iterable, List, Optional, Sequence, Set
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
    shipping_cost: Optional[float] = None  # None = non riportata dall'API, MAI assunta 0

    @property
    def total_price(self) -> Optional[float]:
        """
        Prezzo + spedizione. None se manca il prezzo di listino O la
        spedizione — non assumiamo mai spedizione gratuita per un dato
        mancante (vedi nota di design in testa al file).
        """
        if self.price is None or self.shipping_cost is None:
            return None
        return self.price + self.shipping_cost


def _parse_shipping_cost(item: dict) -> Optional[float]:
    """La Browse API riporta la spedizione in shippingOptions[0].shippingCost."""
    options = item.get("shippingOptions") or []
    if not options:
        return None
    cost = options[0].get("shippingCost", {})
    value = cost.get("value")
    return float(value) if value is not None else None


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
            shipping_cost=_parse_shipping_cost(item),
        ))
    return listings


def search_active_listings_multi(
    queries: Sequence[str],
    access_token: str,
    limit_per_query: int = 50,
    marketplace_id: str = "EBAY_IT",
    http_get: HttpGet = default_http_get,
) -> List[EbayListing]:
    """
    Lancia una ricerca per ciascuna query (varianti IT/EN, nomi alternativi,
    abbreviazioni) e unisce i risultati deduplicando per item_id — la stessa
    inserzione può comparire in più varianti di query, va contata una volta
    sola. Il filtro anti-falsi-positivi va applicato DOPO, con
    filter_relevant_listings, sul pool unito.
    """
    seen: dict = {}
    for q in queries:
        for listing in search_active_listings(
            q, access_token, limit=limit_per_query,
            marketplace_id=marketplace_id, http_get=http_get,
        ):
            if listing.item_id and listing.item_id not in seen:
                seen[listing.item_id] = listing
    return list(seen.values())


def filter_relevant_listings(
    listings: Iterable[EbayListing],
    exclude_terms: Sequence[str] = (),
    include_any_of: Sequence[Sequence[str]] = (),
    include_all: Sequence[str] = (),
) -> List[EbayListing]:
    """
    Filtro anti-falsi-positivi. Priorità dichiarata: in caso di dubbio,
    SCARTA — meglio perdere un'inserzione borderline che segnalare un
    prodotto sbagliato.

    - exclude_terms: se anche UNA sola stringa compare nel titolo (case-
      insensitive), l'inserzione è scartata a prescindere dal resto (es.
      "digital code", "proxy", "custom", "fanmade", nomi di prodotti simili
      ma diversi). Controllato PER PRIMO e ha sempre l'ultima parola.
    - include_all: TUTTI questi termini devono comparire nel titolo (AND).
    - include_any_of: una lista di gruppi; per OGNI gruppo deve comparire
      ALMENO uno dei termini (AND fra i gruppi, OR dentro al gruppo) — utile
      per varianti linguistiche dello stesso concetto, es.
      [["elite trainer box", "etb"], ["30th", "30°", "30 anniversario"]]
      così si accetta sia il nome inglese sia quello italiano, ma sempre
      insieme a un riferimento alla linea "30° anniversario".

    Pensato per essere alimentato dalle liste già definite in keywords.py
    invece di duplicare le parole chiave qui.
    """
    result = []
    for listing in listings:
        title_lower = listing.title.lower()

        if any(term.lower() in title_lower for term in exclude_terms):
            continue

        if include_all and not all(term.lower() in title_lower for term in include_all):
            continue

        if include_any_of:
            groups_ok = all(
                any(term.lower() in title_lower for term in group)
                for group in include_any_of
            )
            if not groups_ok:
                continue

        result.append(listing)
    return result


def select_cheapest(listings: Iterable[EbayListing], top_n: int = 3) -> List[EbayListing]:
    """
    Le top_n inserzioni per prezzo totale (prodotto + spedizione) più basso,
    a PRESCINDERE da seen_item_ids: anche se già segnalate in scansioni
    precedenti, vanno comunque incluse ogni volta se restano tra le più
    economiche — è un segnale "miglior prezzo attuale", non "cosa è cambiato
    dall'ultima scansione".

    Le inserzioni senza total_price calcolabile (prezzo o spedizione
    mancanti) sono escluse dal confronto, non messe in fondo alla lista:
    non possiamo confrontarle in modo affidabile con le altre.
    """
    pricable = [l for l in listings if l.total_price is not None]
    return sorted(pricable, key=lambda l: l.total_price)[:top_n]


def find_new_listings(listings: List[EbayListing], seen_item_ids: Set[str]) -> List[EbayListing]:
    """seen_item_ids va gestito dal chiamante — persistenza vera nel punto 'b'."""
    return [l for l in listings if l.item_id not in seen_item_ids]


def listing_to_evidence(
    listing: EbayListing,
    observed_on: Optional[date] = None,
    reason: Optional[str] = None,
) -> Evidence:
    """
    reason: etichetta opzionale anteposta alla nota (es. "NUOVA",
    "PREZZO MIGLIORE", "NUOVA + PREZZO MIGLIORE") — serve a chi legge
    l'alert a capire SUBITO perché questa inserzione gli viene segnalata,
    invece di doverlo dedurre. Chi chiama questa funzione (orchestrator.py)
    decide l'etichetta in base a quale logica ha selezionato l'inserzione.
    """
    if listing.price is None:
        price_str = "prezzo n/d"
    elif listing.shipping_cost is None:
        price_str = f"{listing.price} {listing.currency} + spedizione n/d"
    else:
        price_str = (
            f"{listing.price} {listing.currency} + {listing.shipping_cost} "
            f"{listing.currency} sped. = {listing.total_price:.2f} {listing.currency} tot."
        )
    tag = f"[{reason}] " if reason else ""
    return Evidence(
        source_type=SourceType.LISTING_CLAIM,
        source_name=f"eBay - inserzione ({listing.seller})",
        observed_on=observed_on or date.today(),
        url=listing.url,
        note=f"{tag}'{listing.title}' — {price_str} — venditore: {listing.seller}",
    )


if __name__ == "__main__":
    def fake_merged_pool() -> List[EbayListing]:
        # Simula il risultato già unito/deduplicato di
        # search_active_listings_multi su più varianti della stessa query.
        return [
            EbayListing("111", "Pokemon 30th Celebration Elite Trainer Box PREORDER",
                        "https://ebay.it/itm/111", 152.51, "EUR", "seller_a", shipping_cost=9.90),
            EbayListing("222", "Pokemon Set Allenatore Fuoriclasse 30 Anniversario ITA",
                        "https://ebay.it/itm/222", 89.00, "EUR", "seller_b", shipping_cost=0.0),
            EbayListing("333", "Pokemon 30th Anniversary Elite Trainer Box ETB SEALED",
                        "https://ebay.it/itm/333", 78.00, "EUR", "seller_c", shipping_cost=None),
            EbayListing("444", "Pokemon 30th Celebration ETB VIDEOGAME digital code",
                        "https://ebay.it/itm/444", 15.00, "EUR", "seller_d", shipping_cost=2.00),
            EbayListing("555", "Pokemon Scarlet Violet Elite Trainer Box (tutt'altra linea)",
                        "https://ebay.it/itm/555", 45.00, "EUR", "seller_e", shipping_cost=5.00),
        ]

    print("=" * 70)
    print("1) Pool unito da più varianti di query (già deduplicato)")
    print("=" * 70)
    pool = fake_merged_pool()
    for l in pool:
        print(f"  · {l.title}")

    print()
    print("=" * 70)
    print("2) Filtro anti-falsi-positivi (exclude ha sempre l'ultima parola)")
    print("=" * 70)
    relevant = filter_relevant_listings(
        pool,
        exclude_terms=["digital code", "scarlet violet"],
        include_any_of=[
            ["elite trainer box", "etb", "allenatore fuoriclasse"],
            ["30th", "30°", "30 anniversario", "celebration"],
        ],
    )
    for l in pool:
        tag = "OK" if l in relevant else "SCARTATA"
        print(f"  · [{tag}] {l.title}")

    print()
    print("=" * 70)
    print("3) Le 3 col prezzo totale più basso, a prescindere da già viste")
    print("   ('333' ha prezzo più basso ma spedizione ignota -> escluso")
    print("   dal confronto, MAI trattato come spedizione gratuita)")
    print("=" * 70)
    for l in select_cheapest(relevant, top_n=3):
        ev = listing_to_evidence(l, observed_on=date(2026, 9, 12))
        print(f"  · {ev.note}")

    print()
    print("=" * 70)
    print("Per confronto: comportamento 'solo nuove' esistente, invariato")
    print("=" * 70)
    new = find_new_listings(relevant, seen_item_ids={"111", "222"})
    for l in new:
        print(f"  · nuova: {l.title}")
