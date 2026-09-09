"""
cardmarket_scanner.py — Scanner prezzi Cardmarket per Pokémon, via tcgdex.dev.

Copertura: SOLO Pokémon. tcgdex.dev è un'API Pokémon-specifica; per Yu-Gi-Oh,
Riftbound e WoW TCG serve un'altra fonte (da individuare — non ancora fatto,
non voglio inventarla senza verificarla come già successo con Cardmarket diretto).

Perché tcgdex.dev e non l'API Cardmarket diretta: quella è riservata a venditori
professionali approvati (stesso gate di eBay/TCGPlayer). tcgdex.dev incorpora i
dati Cardmarket (aggiornati giornalmente, EUR) gratis e senza autenticazione.

Perché AGGREGATE_STAT e non SOLD_COMP: avg1/avg7/avg30 sono medie di vendite
reali su una finestra temporale (metodologia di Cardmarket, non nostra) — un
segnale solido ma aggregato, non una transazione singola verificabile con URL.
"low" è il prezzo di richiesta più basso attivo, NON una vendita: non lo uso
come evidenza da solo.

Il client HTTP è iniettabile: qui lo testiamo con risposte finte (in questo
ambiente non c'è rete); nel tuo GitHub Actions passerai default_http_get, che
usa 'requests' per davvero.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Callable, Optional

from scoring import Evidence, SourceType

TCGDEX_CARD_URL = "https://api.tcgdex.net/v2/en/cards/{card_id}"

HttpGet = Callable[[str], dict]  # url -> JSON già parsato in dict


def default_http_get(url: str) -> dict:
    """
    Implementazione reale per l'uso in produzione (GitHub Actions). Non
    eseguibile in questo sandbox: qui niente rete, si passa un fake a fetch_card_pricing.
    """
    import requests  # import locale: non serve se si usa solo il fake nei test
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    return resp.json()


@dataclass
class CardmarketSnapshot:
    card_id: str
    card_name: str
    unit: str
    avg30: Optional[float]
    trend: Optional[float]
    low: Optional[float]          # prezzo di richiesta più basso — MAI da solo come evidenza
    updated: Optional[datetime]


def fetch_card_pricing(card_id: str, http_get: HttpGet = default_http_get) -> Optional[CardmarketSnapshot]:
    """
    Scarica il pricing di una carta da tcgdex.dev. Restituisce None se Cardmarket
    non ha dati per quella carta (capita per esclusive regionali, carte troppo
    recenti, o EX/Full Art di set vecchi — vedi FAQ tcgdex) — un None esplicito,
    da non confondere con "prezzo zero".
    """
    url = TCGDEX_CARD_URL.format(card_id=card_id)
    data = http_get(url)
    pricing = data.get("pricing", {}) or {}
    cm = pricing.get("cardmarket")
    if cm is None:
        return None

    updated_raw = cm.get("updated")
    updated_dt = None
    if updated_raw:
        updated_dt = datetime.fromisoformat(updated_raw.replace("Z", "+00:00"))

    return CardmarketSnapshot(
        card_id=card_id,
        card_name=data.get("name", card_id),
        unit=cm.get("unit", "EUR"),
        avg30=cm.get("avg30"),
        trend=cm.get("trend"),
        low=cm.get("low"),
        updated=updated_dt,
    )


def snapshot_to_evidence(snap: CardmarketSnapshot, as_of: Optional[date] = None) -> Evidence:
    """
    Converte uno snapshot in Evidence AGGREGATE_STAT. La data di osservazione è
    quella dichiarata da Cardmarket (campo 'updated'), non oggi — così il
    decadimento nel modulo di scoring riflette quanto è vecchio DAVVERO il dato,
    non quando l'abbiamo interrogato noi.
    """
    observed_on = snap.updated.date() if snap.updated else (as_of or date.today())
    note = (
        f"avg30={snap.avg30} {snap.unit} · trend={snap.trend} {snap.unit} · "
        f"low={snap.low} {snap.unit} (low = richiesta attiva, non vendita)"
    )
    return Evidence(
        source_type=SourceType.AGGREGATE_STAT,
        source_name=f"Cardmarket price guide via tcgdex.dev ({snap.card_name})",
        observed_on=observed_on,
        url=TCGDEX_CARD_URL.format(card_id=snap.card_id),
        note=note,
    )


def price_spike_pct(snap: CardmarketSnapshot) -> Optional[float]:
    """
    Scostamento percentuale del trend rispetto alla propria media 30gg.
    Utile come primo filtro grezzo per il claim di 'hype' (non un alert da solo:
    va comunque incrociato con almeno un'altra fonte prima di salire di fascia).
    Restituisce None se manca uno dei due dati o avg30 è zero.
    """
    if snap.trend is None or snap.avg30 in (None, 0):
        return None
    return (snap.trend - snap.avg30) / snap.avg30 * 100.0


if __name__ == "__main__":
    # Demo con risposte HTTP finte (nessuna rete in questo ambiente).
    # Tre casi: carta con spike di prezzo, carta stabile, carta senza pricing.

    def fake_http_get(url: str) -> dict:
        if "swsh1-1" in url:  # carta con hype: trend molto sopra la media 30gg
            return {
                "name": "Grookey (esempio con hype)",
                "pricing": {
                    "cardmarket": {
                        "updated": "2026-09-08T00:42:15.000Z",
                        "unit": "EUR",
                        "avg": 12.0,
                        "low": 9.0,
                        "trend": 22.0,
                        "avg1": 20.0,
                        "avg7": 18.0,
                        "avg30": 12.0,
                    }
                },
            }
        if "swsh1-2" in url:  # carta stabile
            return {
                "name": "Scorbunny (esempio stabile)",
                "pricing": {
                    "cardmarket": {
                        "updated": "2026-09-01T00:00:00.000Z",
                        "unit": "EUR",
                        "avg": 3.0,
                        "low": 2.5,
                        "trend": 3.1,
                        "avg1": 3.0,
                        "avg7": 3.0,
                        "avg30": 3.0,
                    }
                },
            }
        # carta senza dati Cardmarket (es. esclusiva regionale)
        return {"name": "Esclusiva regionale (esempio senza pricing)", "pricing": {}}

    for card_id in ["swsh1-1", "swsh1-2", "swsh1-999"]:
        snap = fetch_card_pricing(card_id, http_get=fake_http_get)
        print("=" * 70)
        print(f"card_id={card_id}")
        if snap is None:
            print("  Nessun dato Cardmarket per questa carta (esclusiva/troppo recente/EX vecchia).")
            continue
        spike = price_spike_pct(snap)
        print(f"  {snap.card_name}: trend={snap.trend} avg30={snap.avg30} {snap.unit}")
        print(f"  scostamento trend vs avg30: {spike:+.1f}%" if spike is not None else "  scostamento: n/d")
        ev = snapshot_to_evidence(snap)
        print(f"  -> Evidence: {ev.source_type.value}, osservata il {ev.observed_on}")
        print(f"     {ev.note}")

    print()
    print("=" * 70)
    print("Chiudo il cerchio: passo l'Evidence del caso 'hype' allo scoring.")
    print("Un solo AGGREGATE_STAT, da solo, resta 'Bassa' — serve corroborazione")
    print("(un'altra fonte, o un secondo marketplace con vendite concluse).")
    print("=" * 70)
    from scoring import score_claim
    hype_snap = fetch_card_pricing("swsh1-1", http_get=fake_http_get)
    result = score_claim("grookey_hype_swsh1_1", [snapshot_to_evidence(hype_snap)], as_of=date(2026, 9, 9))
    print(result.summary())
