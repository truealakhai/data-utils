"""
telegram_alerts.py — Manda un alert Telegram quando un claim SALE di fascia
di affidabilità, usando lo stato persistito per non rimandare lo stesso
alert ogni volta che lo scanner gira (stesso principio del bot Telegram già
in uso nel progetto trading).

Regola di invio (scelta di design, non l'unica possibile — la dico
esplicitamente invece di nasconderla in mezzo al codice):
- Alert SOLO su salita di fascia (Bassa->Media, Media->Alta, o prima volta
  che si raggiunge min_band_to_alert), MAI su un calo.
- Una volta alertato per una fascia, non si rialerta per la STESSA fascia
  anche se il punteggio oscilla dentro quella fascia con scan successivi.
- Se il claim scende e poi risale a una fascia già raggiunta in passato
  (es. era arrivato ad Alta, è sceso, torna a Media), NON rialerta — la
  fascia massima già segnalata resta il riferimento. Scelta conservativa
  per evitare spam; se preferisci un comportamento diverso (es. rialertare
  ad ogni salita anche se già vista) è una riga sola da cambiare qui sotto.
"""

from __future__ import annotations

from datetime import date
from typing import Callable, List, Optional

from scoring import Evidence, ScoreResult, score_claim
from state_store import StateStore

BAND_ORDER = {"Bassa": 0, "Media": 1, "Alta": 2}

TelegramSend = Callable[[str, str], None]  # (chat_id, text) -> None


def make_telegram_sender(bot_token: str) -> TelegramSend:
    """Ritorna una funzione send(chat_id, text) pronta per l'uso reale."""
    def _send(chat_id: str, text: str) -> None:
        import requests
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        resp = requests.post(url, data={
            "chat_id": chat_id, "text": text, "disable_web_page_preview": True,
        })
        resp.raise_for_status()
    return _send


def format_alert(claim_id: str, score: ScoreResult, previous_band: Optional[str]) -> str:
    arrow = f"{previous_band} → {score.band}" if previous_band else score.band
    lines = [f"🚨 {claim_id}", f"Affidabilità: {arrow} ({score.score:.0f}/100)", ""]
    for e in score.evidences[-5:]:  # ultime 5 evidenze, non l'intera storia
        lines.append(f"· [{e.source_type.value}] {e.source_name}: {e.note}")
    if score.reasons:
        lines.append("")
        lines.append("Note: " + "; ".join(score.reasons[:2]))
    return "\n".join(lines)


def process_claim(
    claim_id: str,
    new_evidence: List[Evidence],
    store: StateStore,
    send: TelegramSend,
    chat_id: str,
    min_band_to_alert: str = "Media",
    as_of: Optional[date] = None,
) -> Optional[ScoreResult]:
    """
    Unisce la nuova evidenza a quella già salvata (persistita tra run),
    ricalcola il punteggio sulla storia COMPLETA, e manda un alert solo se
    la fascia è salita rispetto all'ultimo alert inviato per questo claim.
    Ritorna lo ScoreResult (utile per log/debug) o None se non è stato
    mandato nulla — non è un errore, è lo stato normale della maggior parte
    degli scan.
    """
    all_evidence = store.add_evidence(claim_id, new_evidence)
    score = score_claim(claim_id, all_evidence, as_of=as_of)

    previous_band = store.get_last_alerted_band(claim_id)
    is_upgrade = (
        BAND_ORDER[score.band] >= BAND_ORDER[min_band_to_alert]
        and (previous_band is None or BAND_ORDER[score.band] > BAND_ORDER.get(previous_band, -1))
    )

    store.save()  # l'evidenza va salvata comunque, alert o no

    if is_upgrade:
        text = format_alert(claim_id, score, previous_band)
        send(chat_id, text)
        store.set_last_alerted_band(claim_id, score.band)
        store.save()
        return score

    return None


if __name__ == "__main__":
    import os
    import tempfile

    from scoring import SourceType

    tmp_path = os.path.join(tempfile.gettempdir(), "tcg_seeker_alerts_demo.json")
    if os.path.exists(tmp_path):
        os.remove(tmp_path)

    sent_messages = []  # cattura i messaggi invece di chiamare Telegram davvero

    def fake_send(chat_id: str, text: str) -> None:
        sent_messages.append((chat_id, text))

    store = StateStore(tmp_path)
    CLAIM = "grookey_hype_swsh1_1"

    print("=" * 70)
    print("Scan 1: una sola AGGREGATE_STAT — resta 'Bassa', sotto soglia,")
    print("nessun alert")
    print("=" * 70)
    ev1 = [Evidence(SourceType.AGGREGATE_STAT, "Cardmarket via tcgdex", date(2026, 9, 8),
                     note="trend +83% su avg30", marketplace="Cardmarket")]
    result1 = process_claim(CLAIM, ev1, store, fake_send, chat_id="12345")
    print(f"  risultato: {result1.band if result1 else 'nessun alert'} — messaggi inviati finora: {len(sent_messages)}")

    print()
    print("=" * 70)
    print("Scan 2 (run successivo): arriva una fonte community E una vendita")
    print("conclusa reale — la fascia sale a 'Media', QUESTO deve generare")
    print("un alert (nota: community+aggregate_stat da soli non basterebbero,")
    print("15+20=35 punti max, sotto la soglia 40 — serve davvero un terzo")
    print("tipo di fonte con peso più alto per superarla)")
    print("=" * 70)
    store2 = StateStore(tmp_path)
    ev2 = [
        Evidence(SourceType.COMMUNITY, "r/PokemonTCG", date(2026, 9, 9),
                 note="thread con 400+ upvote sulla stessa carta"),
        Evidence(SourceType.SOLD_COMP, "eBay - vendita conclusa", date(2026, 9, 9),
                 url="https://ebay.it/itm/grookey1", note="21.50 EUR", marketplace="eBay"),
    ]
    result2 = process_claim(CLAIM, ev2, store2, fake_send, chat_id="12345", as_of=date(2026, 9, 9))
    print(f"  risultato: {result2.band if result2 else 'nessun alert'} — messaggi inviati finora: {len(sent_messages)}")
    if sent_messages:
        print("\n  --- contenuto dell'alert ---")
        print("  " + sent_messages[-1][1].replace("\n", "\n  "))

    print()
    print("=" * 70)
    print("Scan 3 (run successivo): stessa evidenza di prima, nessuna novità")
    print("— NON deve arrivare un secondo alert per la stessa fascia")
    print("=" * 70)
    store3 = StateStore(tmp_path)
    result3 = process_claim(CLAIM, ev2, store3, fake_send, chat_id="12345", as_of=date(2026, 9, 9))
    print(f"  risultato: {'alert inviato (SBAGLIATO)' if result3 else 'nessun alert (corretto)'} — messaggi totali: {len(sent_messages)}")
