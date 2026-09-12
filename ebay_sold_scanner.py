"""
ebay_sold_scanner.py — Interroga DIRETTAMENTE il filtro "Oggetti venduti"
di eBay (LH_Sold=1&LH_Complete=1), invece di sperare che una ricerca web
generica lo trovi per caso.

PERCHÉ QUESTO FILE ESISTE: scoperta fatta insieme all'utente confrontando
i risultati del bot on-demand con una ricerca manuale — il filtro "Sold
Items" di eBay produce una vista filtrata sul loro database che Google/Bing
non indicizzano bene. La ricerca web generica (quella usata finora da
on_demand_lookup.py) semplicemente non ha accesso a questi dati, non è un
problema di quali parole cercare. L'unico modo per ottenerli davvero è
interrogare quell'URL specifico.

AVVERTENZA IMPORTANTE, dalla stessa verifica fatta con l'utente: **il
filtro "Venduti" di eBay non è impeccabile al 100%** — un'inserzione nella
lista "Venduti" si è rivelata in realtà "chiusa dal venditore, non più
disponibile" aprendo la pagina di dettaglio (non una vendita vera). Questo
scanner legge solo la pagina di LISTA (non apre ogni singolo annuncio per
verificarlo — sarebbe troppe richieste, rischio di blocco), quindi eredita
questo margine di errore. Per questo le evidenze restano comunque soggette
alla stessa regola di corroborazione di sempre — un singolo risultato da
qui non basta a salire oltre "Bassa" da solo, esattamente come per le
altre fonti.

NON VERIFICATO CONTRO L'HTML REALE in questo ambiente (niente rete qui) —
i selettori sotto si basano sulla struttura nota e stabile delle pagine di
ricerca eBay (contenitori "li.s-item"), ma vanno confermati alla prima
esecuzione vera, stesso avviso già dato per Serebii/PokeBeach a suo tempo.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable, List, Optional
from urllib.parse import quote_plus

from scoring import Evidence, SourceType

# .it per la priorità EU/Italia; puoi passare un altro dominio (es. "com")
# se ti serve il mercato USA per la stessa query.
SEARCH_URL_TEMPLATE = "https://www.ebay.{tld}/sch/i.html?_nkw={query}&LH_Sold=1&LH_Complete=1"


def default_http_get(url: str) -> str:
    """
    Implementazione reale. Non eseguibile qui (niente rete).

    Header ampliati — tentativo per il 403 osservato in un run reale, stesso
    principio del fix che ha funzionato per PokeBeach. Qui però le probabilità
    di successo sono più basse: eBay è un sito enterprise, è probabile abbia
    una protezione anti-bot ben più sofisticata di un semplice controllo
    User-Agent (Akamai/PerimeterX o simili) — lo stesso motivo per cui la loro
    API ufficiale sulle vendite concluse è ad accesso ristretto. Se anche
    questo non basta, l'alternativa realistica è uno scraper di terzi a
    pagamento (Apify e simili, ne avevamo parlato molto indietro in questa
    conversazione) — non più un problema di codice nostro da risolvere.
    """
    import requests
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.ebay.it/",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Connection": "keep-alive",
    }
    resp = requests.get(url, timeout=15, headers=headers)
    resp.raise_for_status()
    return resp.text


@dataclass
class EbaySoldListing:
    title: str
    price: float
    currency: str
    sold_on: Optional[date]
    url: str
    seller: str = "sconosciuto"


def build_search_url(query: str, tld: str = "it") -> str:
    return SEARCH_URL_TEMPLATE.format(tld=tld, query=quote_plus(query))


def _parse_price(raw: str) -> tuple:
    """
    Esempi osservati nei tuoi screenshot: 'EUR 3.320,60', 'US $459.99'.
    Gestisce sia il formato EU (punto=migliaia, virgola=decimali) che US.
    """
    raw = raw.strip()
    currency = "EUR" if "EUR" in raw or "€" in raw else ("USD" if "$" in raw or "US" in raw else "")
    digits = re.sub(r"[^\d,.\-]", "", raw)
    if "," in digits and "." in digits:
        # formato EU: 3.320,60 -> 3320.60
        digits = digits.replace(".", "").replace(",", ".")
    elif "," in digits:
        digits = digits.replace(",", ".")
    try:
        return float(digits), currency
    except ValueError:
        return 0.0, currency


_MONTH_MAP = {
    # italiano (eBay.it) — 3 lettere come le mostra eBay
    "gen": 1, "feb": 2, "mar": 3, "apr": 4, "mag": 5, "giu": 6,
    "lug": 7, "ago": 8, "set": 9, "ott": 10, "nov": 11, "dic": 12,
    # inglese, per riuso dello scanner su ebay.com
    "jan": 1, "mar_": 3, "may": 5, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "oct": 10, "dec": 12,
    "feb_": 2, "apr_": 4, "nov_": 11,
}


def _parse_sold_date(raw: str) -> Optional[date]:
    """
    eBay mostra date tipo 'Venduto 23 ago 2026' (o solo '9 ago 2026') a
    seconda della lingua — parsing manuale con mappa esplicita perché
    strptime('%b') dipende dalla lingua di sistema del server, che su
    GitHub Actions non è detto sia italiana (di solito è inglese/C).
    """
    match = re.search(r"(\d{1,2})\s+([A-Za-zàèìòù]{3,})\.?\s+(\d{4})", raw.strip())
    if not match:
        return None
    day, month_raw, year = match.groups()
    month = _MONTH_MAP.get(month_raw.lower()[:3])
    if month is None:
        return None
    try:
        return date(int(year), month, int(day))
    except ValueError:
        return None


def fetch_sold_listings(
    query: str,
    tld: str = "it",
    http_get: Callable[[str], str] = default_http_get,
) -> List[EbaySoldListing]:
    from bs4 import BeautifulSoup

    url = build_search_url(query, tld=tld)
    html = http_get(url)
    soup = BeautifulSoup(html, "html.parser")

    listings = []
    for item in soup.select("li.s-item"):
        title_el = item.select_one(".s-item__title")
        price_el = item.select_one(".s-item__price")
        link_el = item.select_one("a.s-item__link")
        sold_el = item.select_one(".s-item__caption, .s-item__title--tag")  # data vendita, posizione variabile

        if not title_el or not price_el or not link_el:
            continue

        price, currency = _parse_price(price_el.get_text())
        sold_on = _parse_sold_date(sold_el.get_text()) if sold_el else None

        listings.append(EbaySoldListing(
            title=title_el.get_text(strip=True),
            price=price,
            currency=currency,
            sold_on=sold_on,
            url=link_el.get("href", ""),
        ))
    return listings


def listing_to_evidence(listing: EbaySoldListing, as_of: Optional[date] = None) -> Evidence:
    """
    SOLD_COMP — il filtro LH_Sold=1&LH_Complete=1 è pensato per mostrare
    vendite concluse, ma NON è verificato al 100% (vedi avviso in testa al
    file). Etichettato comunque SOLD_COMP, non LISTING_CLAIM, perché è il
    dato più vicino a una vendita reale che possiamo ottenere in automatico
    — la cautela sta nella regola di corroborazione a valle, non nel
    declassare la fonte.
    """
    return Evidence(
        source_type=SourceType.SOLD_COMP,
        source_name=f"eBay - filtro Venduti ({listing.seller})",
        observed_on=listing.sold_on or (as_of or date.today()),
        url=listing.url,
        note=f"'{listing.title}' — {listing.price} {listing.currency}",
        marketplace="eBay",
    )


if __name__ == "__main__":
    # Dati REALI dai tuoi screenshot (non inventati), riformattati come
    # BeautifulSoup li estrarrebbe da li.s-item
    print("=" * 70)
    print("URL che verrebbe interrogato per la tua query:")
    print("=" * 70)
    print(" ", build_search_url("RIFTBOUND teemo FND-196"))

    print()
    print("=" * 70)
    print("Verifica parsing prezzo/data su valori reali osservati")
    print("=" * 70)
    test_cases = [
        ("EUR 3.320,60", "9 ago 2026"),
        ("US $459.99", "19 ago 2026"),
        ("EUR 792,28", "1 lug 2026"),
    ]
    for price_raw, date_raw in test_cases:
        price, currency = _parse_price(price_raw)
        parsed_date = _parse_sold_date(date_raw)
        print(f"  '{price_raw}' -> {price} {currency}  |  '{date_raw}' -> {parsed_date}")
