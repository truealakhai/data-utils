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
    except Exception:
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
    ci sono tante inserzioni di venditori diversi. Qui riusiamo la stessa
    logica di ebay_new_listing_scanner.py (nuove inserzioni = segnale), ma
    interrogando PIÙ query per prodotto — tipicamente una in inglese e una
    in italiano, perché una sola lingua perde gran parte del mercato
    (lezione di sessione: "Elite Trainer Box" vs "Set Allenatore Fuoriclasse").
    Se ebay_token è None (credenziali assenti/non ancora pronte), salta
    silenziosamente — stesso comportamento degli altri scanner eBay.
    """
    from ebay_new_listing_scanner import (
        search_active_listings, find_new_listings, listing_to_evidence,
        default_http_get as ebay_default_http_get,
    )

    results = {}
    if not ebay_token:
        print("  [info] eBay senza token valido — salto il controllo eBay per lo stock")
        return results

    for product in ebay_watchlist:
        for query in product["queries"]:
            seen_key = f"ebay_stock:{product['product_id']}:{query}"
            try:
                listings = search_active_listings(
                    query, access_token=ebay_token,
                    http_get=http_get or ebay_default_http_get,
                )
            except Exception as e:
                print(f"  [ERRORE] eBay query '{query}': {e}")
                continue

            seen = store.get_seen(seen_key)
            new_listings = find_new_listings(listings, seen)
            store.mark_seen(seen_key, {l.item_id for l in listings})

            if new_listings:
                lines = [f"🆕 {product['product_name']} — nuove inserzioni eBay ('{query}'):"]
                for l in new_listings[:5]:  # al massimo 5 per non floodare
                    lines.append(f"  · {l.title} — {l.price} {l.currency} — {l.url}")
                send(chat_id, "\n".join(lines))
            results[seen_key] = f"{len(new_listings)} nuove su {len(listings)} totali"

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
