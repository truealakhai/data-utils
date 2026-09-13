"""
stock_monitor.py — Monitora lo STATO DI STOCK (non le notizie) di prodotti
specifici su rivenditori specifici, per avvisare PRIMA che vada esaurito,
non dopo. Nasce da una lacuna reale di Discovery: quel meccanismo reagisce
a notizie/hype già pubblicate, non allo stato di magazzino in tempo reale.

DIFFERENZA DI DESIGN rispetto agli altri scanner: qui il "cosa monitorare"
non è una query testuale ma un elenco esplicito di (prodotto, rivenditore,
URL) — vedi stock_watchlist.py. Questo elenco va popolato A MANO quando
Discovery segnala qualcosa di interessante (non c'è, per ora, un modo per
sapere in anticipo quali URL di quali rivenditori guardare per un prodotto
appena annunciato) — limite dichiarato, non nascosto.

EURISTICA DI RILEVAMENTO STATO — verificata contro l'HTML reale scaricato
oggi stesso, non ipotizzata:
- NerdStoreItalia e CarteMagic (entrambi WooCommerce/WordPress) espongono
  lo stesso identico meta tag `twitter:data2` con "SOLD OUT"/"Esaurito" —
  probabile plugin comune, quindi probabilmente si generalizza ad altri
  negozi italiani sulla stessa piattaforma (non garantito per tutti).
- Fallback: ricerca testuale di frasi chiave, per piattaforme diverse
  (visto oggi: Baruzcard/Shopify usa "Esaurito" in testo libero, non nel
  meta tag; Maximus.be usa "Op voorraad" per "disponibile").
Questa euristica NON è garantita al 100% su rivenditori mai visti prima —
stesso avviso di sempre per Serebii/PokeBeach: verificare al primo uso
reale, aggiustare se necessario.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Callable, List, Optional

SOLD_OUT_PHRASES = [
    "sold out", "esaurito", "esaurita", "non disponibile",
    "reached its limit", "temporaneamente non disponibile",
]
AVAILABLE_PHRASES = [
    "aggiungi al carrello", "add to cart", "in stock",
    "op voorraad", "disponibile", "preordina ora",
]


def default_http_get(url: str) -> str:
    """Implementazione reale. Non eseguibile qui (niente rete)."""
    import requests
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    resp = requests.get(url, timeout=15, headers=headers)
    resp.raise_for_status()
    return resp.text


def extract_stock_status(html: str) -> Optional[str]:
    """
    Ritorna 'available', 'sold_out', o None se non determinabile.
    Euristica 1 (meta tag) prima, poi fallback testuale — vedi note in testa
    al file su dove ciascuna è stata osservata funzionare davvero.
    """
    meta_match = re.search(r"twitter:data2:\s*(.+)", html, re.IGNORECASE)
    if meta_match:
        val = meta_match.group(1).strip().lower()
        if any(p in val for p in ("sold out", "esaurit")):
            return "sold_out"
        if any(p in val for p in ("disponibil", "in stock")):
            return "available"

    text_lower = html.lower()
    if any(p in text_lower for p in SOLD_OUT_PHRASES):
        return "sold_out"
    if any(p in text_lower for p in AVAILABLE_PHRASES):
        return "available"
    return None


@dataclass
class StockCheck:
    product_id: str
    product_name: str
    retailer_name: str
    url: str
    status: Optional[str]
    checked_on: date


def check_retailer(
    product_id: str,
    product_name: str,
    retailer_name: str,
    url: str,
    http_get: Callable[[str], str] = default_http_get,
) -> StockCheck:
    try:
        html = http_get(url)
        status = extract_stock_status(html)
        if status is None:
            print(f"  [ATTENZIONE] {retailer_name}: pagina letta ma stato non riconosciuto (euristica da rivedere per questo sito)")
    except Exception as e:
        print(f"  [ERRORE] {retailer_name}: {e}")
        status = None
    return StockCheck(product_id, product_name, retailer_name, url, status, date.today())


def format_stock_alert(check: StockCheck, previous_status: Optional[str]) -> Optional[str]:
    """
    Ritorna il testo dell'alert, o None se questa transizione non merita un
    messaggio (es. stato invariato, o non determinabile).
    """
    if check.status is None or check.status == previous_status:
        return None

    if previous_status is None and check.status == "available":
        return (
            f"🆕 {check.product_name}\n"
            f"Preordini aperti su {check.retailer_name}!\n"
            f"{check.url}"
        )
    if previous_status == "available" and check.status == "sold_out":
        return (
            f"⚠️ {check.product_name}\n"
            f"Appena esaurito su {check.retailer_name} — se ne resta qualcuno\n"
            f"altrove, la finestra si sta chiudendo.\n"
            f"{check.url}"
        )
    if previous_status == "sold_out" and check.status == "available":
        return (
            f"🔄 {check.product_name}\n"
            f"Tornato disponibile su {check.retailer_name}!\n"
            f"{check.url}"
        )
    return None


def run_stock_check(watchlist: list, store, clients: dict, send, chat_id: str) -> dict:
    """
    clients: {"http_get": funzione} — stesso schema semplice degli altri
    moduli, un solo client qui perché tutti i rivenditori si controllano
    con un GET diretto, non serve altro.
    """
    results = {}
    for product in watchlist:
        for retailer in product["retailers"]:
            key = f"stock:{product['product_id']}:{retailer['name']}"
            check = check_retailer(
                product["product_id"], product["product_name"],
                retailer["name"], retailer["url"],
                http_get=clients.get("http_get", default_http_get),
            )
            previous = store.get_stock_status(key)
            alert_text = format_stock_alert(check, previous)
            if alert_text:
                send(chat_id, alert_text)
            store.set_stock_status(key, check.status)
            results[key] = f"{previous} -> {check.status}"
    store.save()
    return results


def _legacy_seen_ids(store, product_id: str, queries: list) -> set:
    """
    Prima di questa versione lo stato eBay era tenuto per (product_id,
    query) separatamente — una chiave per ogni variante linguistica. Ora
    che le query sono unite in un'unica ricerca per prodotto, questa
    funzione serve SOLO al primo run dopo l'aggiornamento: unisce gli ID
    già visti sotto le vecchie chiavi, così le inserzioni già note non
    vengono ri-segnalate tutte insieme come 'nuove' il giorno del cambio.
    Le scansioni successive leggono/scrivono solo sulla chiave nuova.
    """
    ids = set()
    for q in queries:
        ids |= store.get_seen(f"ebay_stock:{product_id}:{q}")
    return ids


def _cheapest_signature(listings) -> str:
    """
    Rappresentazione stabile e indipendente dall'ordine delle inserzioni
    passate (di norma le 3 più economiche) — usata SOLO per confrontare
    "sono le stesse del post precedente", non per confrontare i prezzi.
    Se anche un solo item_id cambia, la stringa cambia.
    """
    return ",".join(sorted(l.item_id for l in listings))


def run_ebay_check(
    ebay_watchlist: list,
    store,
    ebay_token: Optional[str],
    send,
    chat_id: str,
    http_get=None,
) -> dict:
    """
    eBay è diverso: non c'è una singola pagina con stato disponibile/esaurito,
    ci sono tante inserzioni di venditori diversi. Per ogni prodotto:

    1. Uniamo TUTTE le query del prodotto (varianti IT/EN) in un'unica
       ricerca deduplicata per item_id (search_active_listings_multi) —
       prima si interrogava una query alla volta e si mandava un messaggio
       separato per ciascuna, perdendo il quadro d'insieme e mostrando solo
       una piccola fetta dei match totali per query.
    2. Filtriamo i falsi positivi con EXCLUDE + EBAY_LISTING_EXCLUDE
       (keywords.py) più gli eventuali "ebay_include_any_of"/"ebay_exclude"
       specifici del prodotto in stock_watchlist.py.
    3. Segnaliamo sia le inserzioni NUOVE (dedup come prima) sia, SEMPRE E
       A PRESCINDERE da cosa sia già stato visto, le 3 col prezzo totale
       (prodotto + spedizione) più basso tra quelle rilevanti — così il
       prezzo migliore non si perde anche quando non è "nuovo".
    4. MA se le 3 più economiche sono ESATTAMENTE le stesse (stessi 3
       item_id, ordine ignorato) dell'ultimo post in cui le abbiamo
       pubblicate, il segnale "PREZZO MIGLIORE" viene saltato per intero
       in questo giro — niente ripetizioni identiche. Se anche solo UNA
       delle 3 cambia, si ripubblicano tutte e 3 (non solo la differenza):
       è una scelta esplicita, il messaggio deve restare "il quadro
       completo attuale", non un diff da ricostruire a mano. Lo snapshot
       di confronto (store.get_stock_status/set_stock_status, chiave
       "ebay_stock_cheapest:<product_id>") si aggiorna SOLO quando il
       segnale viene effettivamente pubblicato — un giro saltato non
       sposta il riferimento, quindi un cambiamento successivo viene
       comunque rilevato rispetto all'ultimo post reale, non all'ultimo
       calcolo. Le eventuali inserzioni "NUOVA" ma fuori dalle 3 più
       economiche non sono toccate da questa regola: continuano ad
       arrivare ogni volta che compaiono, a prescindere dal prezzo.

    Un unico messaggio per prodotto invece di uno per query. Le 'nuove' che
    non sono anche tra le più economiche restano limitate a 5 per non
    floodare.

    Se ebay_token è None (credenziali assenti/non ancora pronte), salta
    silenziosamente — stesso comportamento degli altri scanner eBay.
    """
    from ebay_new_listing_scanner import (
        search_active_listings_multi,
        find_new_listings,
        filter_relevant_listings,
        select_cheapest,
        default_http_get as ebay_default_http_get,
    )
    from keywords import EXCLUDE, EBAY_LISTING_EXCLUDE

    results = {}
    if not ebay_token:
        print("  [info] eBay senza token valido — salto il controllo eBay per lo stock")
        return results

    for product in ebay_watchlist:
        queries = product["queries"]
        merged_key = f"ebay_stock:{product['product_id']}"
        try:
            listings = search_active_listings_multi(
                queries, access_token=ebay_token,
                http_get=http_get or ebay_default_http_get,
            )
        except Exception as e:
            print(f"  [ERRORE] eBay {product['product_name']}: {e}")
            continue

        relevant = filter_relevant_listings(
            listings,
            exclude_terms=EXCLUDE + EBAY_LISTING_EXCLUDE + product.get("ebay_exclude", []),
            include_any_of=product.get("ebay_include_any_of", []),
        )

        seen = store.get_seen(merged_key) | _legacy_seen_ids(store, product["product_id"], queries)
        new_listings = find_new_listings(relevant, seen)
        store.mark_seen(merged_key, {l.item_id for l in relevant})

        cheapest = select_cheapest(relevant, top_n=3)
        new_ids = {l.item_id for l in new_listings}
        cheapest_ids = {l.item_id for l in cheapest}

        def _line(l, reason):
            if l.total_price is not None:
                price_str = f"{l.total_price:.2f} {l.currency} tot."
            elif l.price is not None:
                price_str = f"{l.price} {l.currency} + spedizione n/d"
            else:
                price_str = "prezzo n/d"
            return f"  · [{reason}] {l.title} — {price_str} — {l.url}"

        lines_new_only = [
            _line(l, "NUOVA") for l in relevant
            if l.item_id in new_ids and l.item_id not in cheapest_ids
        ][:5]

        cheapest_key = f"ebay_stock_cheapest:{product['product_id']}"
        cheapest_signature = _cheapest_signature(cheapest)
        last_published_signature = store.get_stock_status(cheapest_key)
        cheapest_unchanged = bool(cheapest) and cheapest_signature == last_published_signature

        if cheapest_unchanged:
            lines_cheapest = []
        else:
            lines_cheapest = [
                _line(l, "NUOVA + PREZZO MIGLIORE" if l.item_id in new_ids else "PREZZO MIGLIORE")
                for l in cheapest
            ]

        all_lines = lines_new_only + lines_cheapest
        if all_lines:
            header = f"🆕 {product['product_name']} — aggiornamento eBay:"
            send(chat_id, "\n".join([header] + all_lines))
            if lines_cheapest:
                store.set_stock_status(cheapest_key, cheapest_signature)

        results[merged_key] = (
            f"{len(new_listings)} nuove, {len(relevant)} rilevanti su "
            f"{len(listings)} totali prima del filtro"
            + (" (prezzo migliore invariato dal post precedente, saltato)" if cheapest_unchanged else "")
        )

    store.save()
    return results


if __name__ == "__main__":
    # Frammenti REALI osservati oggi stesso durante le ricerche (non inventati)
    real_nerdstoreitalia_fragment = """
    meta-twitter:data1: €199.99
    meta-twitter:data2: SOLD OUT
    """
    real_cartemagic_fragment = """
    meta-twitter:data1: 279,95&nbsp;€
    meta-twitter:data2: Esaurito
    """
    real_maximus_fragment = """
    Leverbaar vanaf 16 september 2026
    €159,99
    Pre Order
    Op voorraad
    """
    real_baruzcard_fragment = """
    - Etichetta del prodotto: Esaurito
    Prezzo di vendita €459,80
    """

    print("=" * 70)
    print("Verifica euristica contro i 4 pattern HTML reali di oggi")
    print("=" * 70)
    for name, fragment in [
        ("NerdStoreItalia", real_nerdstoreitalia_fragment),
        ("CarteMagic", real_cartemagic_fragment),
        ("Maximus.be", real_maximus_fragment),
        ("Baruzcard", real_baruzcard_fragment),
    ]:
        status = extract_stock_status(fragment)
        print(f"  {name}: {status}")

    print()
    print("=" * 70)
    print("Demo run_stock_check: simulo un rivenditore che passa da")
    print("'disponibile' a 'esaurito' tra un controllo e l'altro")
    print("=" * 70)
    import os
    import tempfile
    from state_store import StateStore

    tmp_path = os.path.join(tempfile.gettempdir(), "tcg_seeker_stock_demo.json")
    if os.path.exists(tmp_path):
        os.remove(tmp_path)
    store = StateStore(tmp_path)

    sent_messages = []
    def fake_send(chat_id, text):
        sent_messages.append(text)

    fake_watchlist = [{
        "product_id": "test_product",
        "product_name": "Prodotto Test",
        "retailers": [{"name": "NegozioTest", "url": "https://esempio.it/prodotto"}],
    }]

    # Check 1: disponibile (prima volta vista = preordine appena aperto)
    def http_get_available(url):
        return "aggiungi al carrello — disponibile ora"
    run_stock_check(fake_watchlist, store, {"http_get": http_get_available}, fake_send, "12345")
    print(f"  dopo check 1 (disponibile): {len(sent_messages)} alert — {sent_messages}")

    # Check 2: stesso stato, nessun nuovo alert
    store2 = StateStore(tmp_path)
    run_stock_check(fake_watchlist, store2, {"http_get": http_get_available}, fake_send, "12345")
    print(f"  dopo check 2 (ancora disponibile, invariato): {len(sent_messages)} alert (deve restare 1)")

    # Check 3: ora esaurito — QUESTO deve generare l'alert critico
    def http_get_sold_out(url):
        return "meta-twitter:data2: Esaurito"
    store3 = StateStore(tmp_path)
    run_stock_check(fake_watchlist, store3, {"http_get": http_get_sold_out}, fake_send, "12345")
    print(f"  dopo check 3 (esaurito): {len(sent_messages)} alert (deve salire a 2)")
    print(f"\n  ultimo alert:\n  {sent_messages[-1]}")
