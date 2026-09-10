"""
tcgcsv_scanner.py — Scanner generico per tcgcsv.com, mirror gratuito e
community-maintained dei prezzi TCGPlayer. Nessuna API key richiesta.

VERIFICATO sui docs ufficiali (tcgcsv.com/docs), non a memoria:
- GET https://tcgcsv.com/tcgplayer/categories → elenco categorie (giochi),
  es. {"categoryId": 3, "name": "Pokemon", ...}
- GET https://tcgcsv.com/tcgplayer/{categoryId}/{groupId}/prices → prezzi
  per un set specifico, es. https://tcgcsv.com/tcgplayer/3/3170/prices
  → {"results": [{"productId":..., "lowPrice":..., "midPrice":...,
     "highPrice":..., "marketPrice":..., "subTypeName":...}]}

NON verificato (inferito dal pattern generale "categories, groups, products,
prices" descritto sulla loro pagina, non da un URL di esempio specifico —
va controllato alla prima esecuzione reale):
- GET https://tcgcsv.com/tcgplayer/{categoryId}/groups → elenco set nella
  categoria (serve per trovare il groupId di un set dato il nome)
- GET https://tcgcsv.com/tcgplayer/{categoryId}/{groupId}/products → nomi
  carta associati ai productId (le /prices da sole danno solo ID numerici,
  senza nome — serve incrociarle con /products per sapere DI CHE CARTA si
  tratta)

Dati in USD (fonte TCGPlayer) — stesso limite di sempre per la priorità EU.
Prezzi = market/low/mid/high aggregati, non vendite singole: AGGREGATE_STAT.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Callable, Dict, List, Optional

from scoring import Evidence, SourceType

BASE_URL = "https://tcgcsv.com/tcgplayer"

HttpGet = Callable[[str], dict]  # url -> JSON parsato


def default_http_get(url: str) -> dict:
    """Implementazione reale. Non eseguibile qui (niente rete)."""
    import requests
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    return resp.json()


def fetch_categories(http_get: HttpGet = default_http_get) -> Dict[str, int]:
    """Ritorna {nome_gioco: categoryId}. Pokemon=3 confermato dal loro esempio."""
    data = http_get(f"{BASE_URL}/categories")
    return {c["name"]: c["categoryId"] for c in data.get("results", [])}


def fetch_groups(category_id: int, http_get: HttpGet = default_http_get) -> Dict[str, int]:
    """
    NON VERIFICATO — endpoint inferito, non da un esempio confermato.
    Ritorna {nome_set: groupId}.
    """
    data = http_get(f"{BASE_URL}/{category_id}/groups")
    return {g["name"]: g["groupId"] for g in data.get("results", [])}


def fetch_products(category_id: int, group_id: int, http_get: HttpGet = default_http_get) -> Dict[int, str]:
    """NON VERIFICATO — endpoint inferito. Ritorna {productId: nome_carta}."""
    data = http_get(f"{BASE_URL}/{category_id}/{group_id}/products")
    return {p["productId"]: p["name"] for p in data.get("results", [])}


@dataclass
class TcgcsvPriceRow:
    product_id: int
    sub_type: str  # es. "Normal", "Holofoil", "Reverse Holofoil"
    low: Optional[float]
    mid: Optional[float]
    high: Optional[float]
    market: Optional[float]


def fetch_group_prices(
    category_id: int,
    group_id: int,
    http_get: HttpGet = default_http_get,
) -> List[TcgcsvPriceRow]:
    """VERIFICATO — schema confermato dall'esempio ufficiale tcgcsv.com/docs."""
    data = http_get(f"{BASE_URL}/{category_id}/{group_id}/prices")
    rows = []
    for r in data.get("results", []):
        rows.append(TcgcsvPriceRow(
            product_id=r["productId"],
            sub_type=r.get("subTypeName", "Normal"),
            low=r.get("lowPrice"),
            mid=r.get("midPrice"),
            high=r.get("highPrice"),
            market=r.get("marketPrice"),
        ))
    return rows


def price_row_to_evidence(
    row: TcgcsvPriceRow,
    card_name: str,
    set_name: str,
    as_of: Optional[date] = None,
) -> Optional[Evidence]:
    if row.market is None:
        return None
    return Evidence(
        source_type=SourceType.AGGREGATE_STAT,
        source_name=f"TCGCSV/TCGPlayer - {card_name} ({set_name}, {row.sub_type})",
        observed_on=as_of or date.today(),
        url=f"{BASE_URL}/{row.product_id}",  # riferimento indicativo al productId, non una pagina reale
        note=f"market={row.market} USD, low={row.low}, high={row.high}",
        marketplace="TCGPlayer (via TCGCSV)",
    )


if __name__ == "__main__":
    def fake_http_get(url: str) -> dict:
        if url.endswith("/3/3170/prices"):
            # Esempio VERO dalla documentazione ufficiale tcgcsv.com/docs
            return {
                "success": True,
                "results": [
                    {"productId": 451784, "lowPrice": 0.1, "midPrice": 0.51,
                     "highPrice": 25.51, "marketPrice": 0.53, "subTypeName": "Holofoil"},
                    {"productId": 451784, "lowPrice": 0.35, "midPrice": 0.7,
                     "highPrice": 2.99, "marketPrice": 0.74, "subTypeName": "Reverse Holofoil"},
                ],
            }
        if url.endswith("/3/3170/products"):
            return {"results": [{"productId": 451784, "name": "Pikachu ex"}]}
        return {}

    print("=" * 70)
    print("Set Pokémon 3170 (esempio reale dai docs), incrocio prezzi+nomi")
    print("=" * 70)
    prices = fetch_group_prices(3, 3170, http_get=fake_http_get)
    names = fetch_products(3, 3170, http_get=fake_http_get)

    for row in prices:
        card_name = names.get(row.product_id, f"prodotto #{row.product_id}")
        ev = price_row_to_evidence(row, card_name, "Set 3170", as_of=date(2026, 9, 9))
        if ev:
            print(f"  · {ev.note} — {ev.source_name}")
