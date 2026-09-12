"""
state_store.py — Persistenza dello stato tra esecuzioni.

Stesso schema mentale del bot Kraken (stato_btc.json): un file JSON, non un
database — coerente con l'infrastruttura che già usi (GitHub Actions + file
di stato, letto/scritto ad ogni run schedulato).

Tiene tre cose distinte:
1. "seen" — set di ID già processati per ogni scanner (URL, item_id eBay,
   post_id Reddit...). Usato dai vari find_new_* di ogni scanner per non
   ri-segnalare la stessa cosa due volte.
2. "evidence" — tutte le Evidence accumulate per ogni claim_id, nel tempo.
   Fondamentale: lo scoring deve vedere la STORIA intera di un claim, non
   solo l'ultimo scan, altrimenti il decadimento e la regola dei 2 tipi di
   fonte non hanno senso (perderemmo evidenza vecchia ma ancora attiva).
3. "last_alerted_band" — l'ultima fascia (Alta/Media/Bassa) per cui abbiamo
   già mandato un alert Telegram per quel claim, per non spammare lo stesso
   avviso ogni volta che lo scanner gira.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional, Set

from scoring import Evidence


class StateStore:
    def __init__(self, path: str):
        self.path = Path(path)
        self._data = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"seen": {}, "evidence": {}, "last_alerted_band": {}}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    # --- ID già visti, per scanner ---

    def get_seen(self, scanner_name: str) -> Set[str]:
        return set(self._data["seen"].get(scanner_name, []))

    def mark_seen(self, scanner_name: str, ids: Set[str]) -> None:
        existing = self.get_seen(scanner_name)
        existing |= ids
        self._data["seen"][scanner_name] = sorted(existing)

    # --- evidence per claim ---

    def get_evidence(self, claim_id: str) -> List[Evidence]:
        raw = self._data["evidence"].get(claim_id, [])
        return [Evidence.from_dict(e) for e in raw]

    def add_evidence(self, claim_id: str, new_evidences: List[Evidence]) -> List[Evidence]:
        """
        Aggiunge nuova evidenza deduplicando su URL (o, se l'URL manca, su
        source_name+data+nota). Ritorna la lista COMPLETA aggiornata — è
        quella da passare a score_claim, non solo new_evidences.
        """
        existing = self.get_evidence(claim_id)
        existing_keys = {self._evidence_key(e) for e in existing}

        for e in new_evidences:
            key = self._evidence_key(e)
            if key not in existing_keys:
                existing.append(e)
                existing_keys.add(key)

        self._data["evidence"][claim_id] = [e.to_dict() for e in existing]
        return existing

    @staticmethod
    def _evidence_key(e: Evidence) -> tuple:
        # (url, source_name) e non solo url: più evidenze possono condividere
        # la stessa URL (es. 4 prezzi di marketplace diversi dalla STESSA
        # risposta YGOPRODeck) senza essere duplicati tra loro — bug reale
        # trovato testando l'orchestratore con lo scanner Yu-Gi-Oh, non
        # ipotetico.
        if e.url:
            return (e.url, e.source_name)
        return (e.source_name, e.observed_on.isoformat(), e.note)

    # --- ultima fascia per cui abbiamo alertato ---

    def get_last_alerted_band(self, claim_id: str) -> Optional[str]:
        return self._data["last_alerted_band"].get(claim_id)

    def set_last_alerted_band(self, claim_id: str, band: str) -> None:
        self._data["last_alerted_band"][claim_id] = band

    # --- stato di stock per prodotto+rivenditore (stock_monitor.py) ---

    def get_stock_status(self, key: str) -> Optional[str]:
        return self._data.setdefault("stock_status", {}).get(key)

    def set_stock_status(self, key: str, status: Optional[str]) -> None:
        self._data.setdefault("stock_status", {})[key] = status


if __name__ == "__main__":
    import os
    import tempfile
    from datetime import date

    from scoring import SourceType

    tmp_path = os.path.join(tempfile.gettempdir(), "tcg_seeker_state_demo.json")
    if os.path.exists(tmp_path):
        os.remove(tmp_path)

    store = StateStore(tmp_path)

    print("=" * 70)
    print("Scan 1: una prima evidenza SOLD_COMP per 'jinx_riftbound'")
    print("=" * 70)
    ev_scan1 = [Evidence(
        SourceType.SOLD_COMP, "eBay - vendita conclusa", date(2026, 9, 1),
        url="https://ebay.it/itm/aaa", note="12.45 EUR", marketplace="eBay",
    )]
    all_ev = store.add_evidence("jinx_riftbound", ev_scan1)
    store.save()
    print(f"  evidenze totali salvate: {len(all_ev)}")

    print()
    print("=" * 70)
    print("Scan 2 (run successivo, nuovo processo Python): ricarico lo stato")
    print("da disco e aggiungo una SECONDA evidenza da un marketplace diverso")
    print("=" * 70)
    store2 = StateStore(tmp_path)  # simula un nuovo processo/esecuzione
    ev_scan2 = [Evidence(
        SourceType.SOLD_COMP, "Cardmarket - vendita conclusa", date(2026, 9, 8),
        url="https://cardmarket.com/itm/bbb", note="12.60 EUR", marketplace="Cardmarket",
    )]
    all_ev2 = store2.add_evidence("jinx_riftbound", ev_scan2)
    store2.save()
    print(f"  evidenze totali dopo il merge: {len(all_ev2)} (1 vecchia + 1 nuova, persistite tra run)")

    print()
    print("=" * 70)
    print("Scan 3: la STESSA evidenza dello scan 2 arriva di nuovo (lo scanner")
    print("l'ha ri-trovata) — deve essere deduplicata, non raddoppiata")
    print("=" * 70)
    store3 = StateStore(tmp_path)
    all_ev3 = store3.add_evidence("jinx_riftbound", ev_scan2)  # stessa URL di prima
    print(f"  evidenze totali dopo il tentativo di duplicato: {len(all_ev3)} (invariato, corretto)")
