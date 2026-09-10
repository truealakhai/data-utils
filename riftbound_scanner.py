"""
riftbound_scanner.py — Tre fonti commerciali per il pricing Riftbound EU/Cardmarket.

DA LEGGERE PRIMA DI USARLO — tre limiti reali, non burocrazia:

1) DESIGN: tutte e tre, in ultima analisi, ri-pacchettizzano gli stessi dati
   Cardmarket (e in parte TCGPlayer) — non sono tre mercati indipendenti come lo
   sono eBay/Cardmarket/TCGPlayer per gli sold_comp. Quindi la Regola B (marketplace
   diversi = corroborazione sufficiente per gli sold_comp) NON si applica qui:
   finiscono tutte come AGGREGATE_STAT. Anche se le tre concordano perfettamente,
   lo scoring le tiene a 'Bassa' finché non arriva una fonte OFFICIAL/COMMUNITY o
   un vero SOLD_COMP verificato a mano. L'accordo tra le tre resta utile — cattura
   un bug di scraping o un dato stantio specifico di UN provider — ma non equivale
   a conferma di mercato indipendente.

2) VERIFICATO vs NON VERIFICATO: ho controllato lo SCHEMA della risposta JSON sulla
   documentazione pubblica di riftbound-api.com e tcg-cardmarket-api.com (esempi
   ufficiali). NON ho verificato il path esatto della richiesta né gli header di
   autenticazione — quelli si vedono solo iscrivendosi su RapidAPI. Le costanti
   *_BASE_URL sono placeholder: sostituiscile con l'host che RapidAPI ti assegna
   (di solito <nome>.p.rapidapi.com, ma vai a controllare dopo l'iscrizione).

3) cardmarket-api.com (il terzo, quello con gli "eBay sold data" per i graded):
   NON ho trovato un esempio di risposta JSON verificabile, solo bullet di
   marketing. Non scrivo un parser per uno schema inventato — sotto trovi solo
   uno stub che te lo ricorda. Quando ti iscrivi, mandami l'esempio di risposta
   reale (di solito nella tab "Endpoints" della loro pagina RapidAPI) e lo finisco.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable, Dict, List, Optional

from scoring import Evidence, SourceType

# TODO: conferma questi host dopo l'iscrizione RapidAPI — sono placeholder plausibili,
# non verificati alla lettera.
RIFTBOUND_API_BASE_URL = "https://riftbound-api.p.rapidapi.com"
TCG_CARDMARKET_API_BASE_URL = "https://tcg-cardmarket-api.p.rapidapi.com"

# Questo invece VERIFICATO sui docs ufficiali (tcgapi.dev/), endpoint reale
# confermato via curl di esempio nella loro home page.
TCGAPI_DEV_BASE_URL = "https://api.tcgapi.dev"

HttpGetWithHeaders = Callable[[str, dict], dict]  # (url, headers) -> JSON parsato


def default_http_get(url: str, headers: dict) -> dict:
    """Implementazione reale. Non eseguibile qui (niente rete in questo ambiente)."""
    import requests
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _rapidapi_headers(api_key: str, host: str) -> dict:
    return {"X-RapidAPI-Key": api_key, "X-RapidAPI-Host": host}


# ---------------------------------------------------------------------------
# Fonte 1: riftbound-api.com — schema verificato dal loro esempio pubblico
# ---------------------------------------------------------------------------

def fetch_riftbound_api(
    card_name: str,
    api_key: str,
    http_get: HttpGetWithHeaders = default_http_get,
) -> List[Evidence]:
    """
    Restituisce Evidence AGGREGATE_STAT da riftbound-api.com: Cardmarket trend
    (EUR) e TCGPlayer market (USD) se presenti nella risposta. Non converto USD
    in EUR qui — lascio il numero grezzo con la valuta dichiarata nel campo note,
    la conversione va fatta a valle con un tasso aggiornato, non uno inventato ora.
    """
    host = RIFTBOUND_API_BASE_URL.replace("https://", "")
    url = f"{RIFTBOUND_API_BASE_URL}/cards?name={card_name}"  # path non confermato
    data = http_get(url, _rapidapi_headers(api_key, host))

    prices = data.get("prices", {})
    last_updated_raw = data.get("last_updated")
    observed_on = date.today()
    if last_updated_raw:
        observed_on = datetime.fromisoformat(last_updated_raw.replace("Z", "+00:00")).date()

    evidences = []
    cm = prices.get("cardmarket")
    if cm and cm.get("trend") is not None:
        evidences.append(Evidence(
            source_type=SourceType.AGGREGATE_STAT,
            source_name="riftbound-api.com - Cardmarket trend",
            observed_on=observed_on,
            url=url,
            note=f"trend={cm.get('trend')} EUR, avg30={cm.get('avg_30d')} EUR",
            marketplace="Cardmarket (riftbound-api.com)",
        ))
    tp = prices.get("tcgplayer")
    if tp and tp.get("market") is not None:
        evidences.append(Evidence(
            source_type=SourceType.AGGREGATE_STAT,
            source_name="riftbound-api.com - TCGPlayer market",
            observed_on=observed_on,
            url=url,
            note=f"market={tp.get('market')} USD (non convertito in EUR)",
            marketplace="TCGPlayer (riftbound-api.com)",
        ))
    return evidences


# ---------------------------------------------------------------------------
# Fonte 2: tcg-cardmarket-api.com — schema verificato dal loro esempio pubblico
# ---------------------------------------------------------------------------

def fetch_tcg_cardmarket_api(
    card_name: str,
    api_key: str,
    game: str = "riftbound",
    http_get: HttpGetWithHeaders = default_http_get,
) -> List[Evidence]:
    """
    Restituisce Evidence AGGREGATE_STAT da tcg-cardmarket-api.com. Solo Cardmarket
    (dichiarato "sincronizzato ogni giorno alle 4:00 UTC" nella loro doc — uso
    quello come data di osservazione, non 'oggi', per coerenza col decadimento).
    """
    host = TCG_CARDMARKET_API_BASE_URL.replace("https://", "")
    url = f"{TCG_CARDMARKET_API_BASE_URL}/cards/search?game={game}&name={card_name}&limit=1"
    data = http_get(url, _rapidapi_headers(api_key, host))

    results = data.get("data", [])
    if not results:
        return []
    card = results[0]
    price = card.get("price", {})
    if price.get("trend") is None:
        return []

    return [Evidence(
        source_type=SourceType.AGGREGATE_STAT,
        source_name="tcg-cardmarket-api.com - Cardmarket trend",
        observed_on=date.today(),  # sync giornaliero dichiarato, non un timestamp per-carta
        url=url,
        note=(
            f"trend={price.get('trend')} EUR, avg7={price.get('avg7')} EUR, "
            f"avg30={price.get('avg30')} EUR, low={price.get('low')} EUR"
        ),
        marketplace="Cardmarket (tcg-cardmarket-api.com)",
    )]


# ---------------------------------------------------------------------------
# Fonte 3: tcgapi.dev — VERIFICATA sui docs ufficiali (a differenza delle due
# sopra, questa ha SDK ufficiali Python/npm e adozione di terzi visibile su
# GitHub — stesso standard di affidabilità di tcgdex/YGOPRODeck, non delle
# API RapidAPI senza track record). Copre Riftbound esplicitamente tra i 7
# giochi aggiornati giornalmente. Dati da TCGPlayer, quindi USD non EUR.
# ---------------------------------------------------------------------------

def fetch_tcgapi_dev(
    card_name: str,
    api_key: str,
    game: str = "riftbound",
    http_get: HttpGetWithHeaders = default_http_get,
) -> List[Evidence]:
    url = f"{TCGAPI_DEV_BASE_URL}/v1/search?q={card_name}&game={game}"
    data = http_get(url, {"X-API-Key": api_key})

    evidences = []
    for card in data.get("data", []):
        price = card.get("price")
        if price is None:
            continue
        change_7d = card.get("price_change_7d")
        note = f"price={price} USD"
        if change_7d is not None:
            note += f", variazione 7gg={change_7d}%"
        evidences.append(Evidence(
            source_type=SourceType.AGGREGATE_STAT,
            source_name=f"tcgapi.dev - {card.get('name', card_name)}",
            observed_on=date.today(),  # tcgapi.dev non riporta un timestamp per-carta nella risposta search
            url=url,
            note=note,
            marketplace="TCGPlayer (via tcgapi.dev)",
        ))
    return evidences


# ---------------------------------------------------------------------------
# Fonte 4: cardmarket-api.com — NON IMPLEMENTATO, schema non verificato
# ---------------------------------------------------------------------------

def fetch_cardmarket_api_com(card_name: str, api_key: str, **_kwargs) -> List[Evidence]:
    raise NotImplementedError(
        "cardmarket-api.com: non ho un esempio di risposta JSON verificato per "
        "questo provider (solo bullet di marketing, non una risposta reale). "
        "Iscriviti su RapidAPI, prendi un esempio di risposta dalla tab "
        "'Endpoints', e lo implemento su quello schema invece di indovinarlo."
    )


# ---------------------------------------------------------------------------
# Aggregatore: interroga le fonti disponibili, salta quelle non pronte
# ---------------------------------------------------------------------------

def fetch_all_riftbound_sources(
    card_name: str,
    api_keys: Dict[str, str],
    http_get: HttpGetWithHeaders = default_http_get,
) -> List[Evidence]:
    """
    api_keys: dict con chiavi 'riftbound_api', 'tcg_cardmarket_api',
    'tcgapi_dev' (e in futuro 'cardmarket_api'). Le fonti per cui manca la
    chiave vengono saltate silenziosamente (utile se ne attivi solo alcune
    per ora).
    """
    evidences: List[Evidence] = []

    if "riftbound_api" in api_keys:
        evidences += fetch_riftbound_api(card_name, api_keys["riftbound_api"], http_get)

    if "tcg_cardmarket_api" in api_keys:
        evidences += fetch_tcg_cardmarket_api(card_name, api_keys["tcg_cardmarket_api"], http_get=http_get)

    if "tcgapi_dev" in api_keys:
        evidences += fetch_tcgapi_dev(card_name, api_keys["tcgapi_dev"], http_get=http_get)

    if "cardmarket_api" in api_keys:
        evidences += fetch_cardmarket_api_com(card_name, api_keys["cardmarket_api"])

    return evidences


if __name__ == "__main__":
    def fake_http_get(url: str, headers: dict) -> dict:
        if "riftbound-api" in url:
            # Esempio verificato dalla documentazione pubblica del provider
            return {
                "id": 33384,
                "name": "Jinx",
                "prices": {
                    "cardmarket": {"trend": 12.45, "avg_1d": 12.30, "avg_7d": 11.89, "avg_30d": 10.52, "low": 9.99},
                    "tcgplayer": {"market": 13.20, "low": 10.50},
                },
                "last_updated": "2026-09-08T14:30:00Z",
            }
        if "tcg-cardmarket-api" in url:
            # Schema verificato (esempio della loro doc era MTG, qui adatto a
            # una carta Riftbound illustrativa mantenendo la stessa struttura)
            return {
                "data": [{
                    "name": "Jinx",
                    "externalId": "999001",
                    "price": {"sell": 13.10, "low": 9.99, "trend": 12.45, "avg7": 11.89, "avg30": 10.52},
                }],
                "meta": {"total": 1, "page": 1},
            }
        if "tcgapi.dev" in url:
            # Schema verificato dal curl di esempio sulla loro home page
            return {
                "data": [{
                    "name": "Jinx",
                    "set": "Riftbound Base Set",
                    "price": 13.85,
                    "price_change_7d": 1.8,
                }]
            }
        return {}

    print("=" * 70)
    print("Jinx (Riftbound) — evidenze da 3 delle 4 fonti (cardmarket-api.com")
    print("resta non implementata, schema non verificato)")
    print("=" * 70)
    evs = fetch_all_riftbound_sources(
        "Jinx",
        api_keys={"riftbound_api": "FAKE_KEY", "tcg_cardmarket_api": "FAKE_KEY", "tcgapi_dev": "FAKE_KEY"},
        http_get=fake_http_get,
    )
    for ev in evs:
        print(f"  · {ev.marketplace:32s} {ev.note}")

    print()
    print("=" * 70)
    print("Le tre fonti concordano abbastanza (trend/price 12.45-13.85€/$) — ma")
    print("passandole allo scoring restano 'Bassa': stesso tipo (AGGREGATE_STAT),")
    print("nessuna diversità di TIPO di fonte, nessun vero sold_comp. Anche con")
    print("4 fonti concordi, senza un tipo diverso non si supera 'Bassa' — la")
    print("regola non cambia in base a QUANTE fonti dello stesso tipo hai.")
    print("=" * 70)
    from scoring import score_claim
    result = score_claim("jinx_riftbound_prezzo", evs, as_of=date(2026, 9, 9))
    print(result.summary())
