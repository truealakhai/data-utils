"""
scoring.py — Modulo di scoring/cross-check per il TCG seeker.

Idea di fondo (decisa in sessione):
- Ogni "claim" (es. "tiratura limitata a 5000 pezzi", "prezzo secondario in forte
  salita", "premio esclusivo di torneo") viene sostenuto da una lista di evidenze.
- Ogni evidenza ha un TIPO di fonte, con un peso base e una finestra di decadimento
  diversa (una vendita conclusa "scade" prima di un comunicato ufficiale).
- Una sola fonte, per quanti punti valga, non può MAI superare la fascia "Bassa":
  serve corroborazione da almeno due tipi di fonte indipendenti.
- Il punteggio finale è tagliato a 95 (mai certezza assoluta) e mappato su tre
  fasce: Alta / Media / Bassa.

Questo modulo non fa scraping né chiamate di rete: prende in input le evidenze
già raccolte dagli scanner (che scriveremo dopo, uno per fonte) e restituisce
un punteggio riproducibile e ispezionabile — la stessa logica di rigore già in
uso nel bot di trading (walk-forward/permutation prima di promuovere un filtro
a REAL): qui, corroborazione multipla prima di promuovere un alert.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date
from enum import Enum
from typing import Dict, List, Optional


class SourceType(Enum):
    """Tipi di fonte riconosciuti, in ordine di affidabilità intrinseca."""
    OFFICIAL = "official"            # publisher / organizzatore torneo (fonte primaria)
    COMMUNITY = "community"          # sito community/news storico e affidabile
    SOLD_COMP = "sold_comp"          # vendita CONCLUSA verificata (non prezzo di richiesta)
    AGGREGATE_STAT = "aggregate_stat"  # statistica aggregata di terzi (es. price guide
                                        # Cardmarket: low/avg/trend) — NON una singola
                                        # transazione verificata, metodologia altrui
    LISTING_CLAIM = "listing_claim"  # claim di un singolo rivenditore/inserzione, non verificato


# punti base e giorni di decadimento (oltre i quali il peso scende a zero) per tipo fonte
SOURCE_WEIGHTS: Dict[SourceType, Dict[str, int]] = {
    SourceType.OFFICIAL:        {"points": 40, "decay_days": 180},
    SourceType.COMMUNITY:       {"points": 20, "decay_days": 120},
    SourceType.SOLD_COMP:       {"points": 25, "decay_days": 45},
    SourceType.AGGREGATE_STAT:  {"points": 15, "decay_days": 30},
    SourceType.LISTING_CLAIM:   {"points": 5,  "decay_days": 30},
}

MAX_SCORE = 95                        # tetto: mai certezza assoluta
MIN_DISTINCT_SOURCES_TO_ESCALATE = 2  # servono almeno 2 TIPI di fonte diversi...
MIN_INDEPENDENT_MARKETPLACES = 2      # ...OPPURE (regola B, decisa in sessione) almeno
                                       # 2 vendite concluse da marketplace indipendenti,
                                       # anche senza fonte ufficiale/community
BASSA_CEILING = 39                    # sotto la soglia di escalation, non si supera "Bassa"

BAND_ALTA = "Alta"
BAND_MEDIA = "Media"
BAND_BASSA = "Bassa"


@dataclass
class Evidence:
    """Una singola evidenza a sostegno (o contro) un claim."""
    source_type: SourceType
    source_name: str          # es. "Cardmarket - vendita conclusa", "YGOrganization"
    observed_on: date         # data in cui il dato è stato osservato/pubblicato
    url: str = ""
    note: str = ""
    marketplace: str = ""     # SOLO per SOLD_COMP: es. "eBay", "TCGPlayer", "Cardmarket".
                               # Serve a distinguere vendite concluse su pool di
                               # compratori davvero indipendenti (vedi regola B sotto).

    def to_dict(self) -> dict:
        d = asdict(self)
        d["source_type"] = self.source_type.value
        d["observed_on"] = self.observed_on.isoformat()
        return d

    @staticmethod
    def from_dict(d: dict) -> "Evidence":
        return Evidence(
            source_type=SourceType(d["source_type"]),
            source_name=d["source_name"],
            observed_on=date.fromisoformat(d["observed_on"]),
            url=d.get("url", ""),
            note=d.get("note", ""),
            marketplace=d.get("marketplace", ""),
        )


@dataclass
class ScoreResult:
    claim_id: str
    score: float
    band: str
    distinct_source_types: int
    reasons: List[str] = field(default_factory=list)
    evidences: List[Evidence] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "claim_id": self.claim_id,
            "score": round(self.score, 1),
            "band": self.band,
            "distinct_source_types": self.distinct_source_types,
            "reasons": self.reasons,
            "evidence": [e.to_dict() for e in self.evidences],
        }

    def summary(self) -> str:
        lines = [f"[{self.band}] {self.claim_id} — score {self.score:.1f}/100"]
        for r in self.reasons:
            lines.append(f"  - {r}")
        for e in self.evidences:
            lines.append(f"  · {e.source_type.value:14s} {e.source_name} ({e.observed_on})")
        return "\n".join(lines)


def _decayed_weight(points: float, decay_days: int, age_days: int) -> float:
    """Decadimento lineare: peso pieno a giorno 0, zero a decay_days."""
    if age_days <= 0:
        return float(points)
    if age_days >= decay_days:
        return 0.0
    return points * (1 - age_days / decay_days)


def score_claim(
    claim_id: str,
    evidences: List[Evidence],
    as_of: Optional[date] = None,
) -> ScoreResult:
    """
    Calcola il punteggio di affidabilità di un claim a partire dalle evidenze
    raccolte. Non fa I/O: puro calcolo, quindi facilmente testabile.
    """
    as_of = as_of or date.today()

    if not evidences:
        return ScoreResult(claim_id, 0.0, BAND_BASSA, 0, ["nessuna evidenza raccolta"], [])

    total = 0.0
    reasons: List[str] = []
    active_types = set()               # tipi con almeno un'evidenza non decaduta
    active_sold_marketplaces = set()   # marketplace distinti con SOLD_COMP non decaduto

    for e in evidences:
        cfg = SOURCE_WEIGHTS[e.source_type]
        age_days = (as_of - e.observed_on).days
        w = _decayed_weight(cfg["points"], cfg["decay_days"], age_days)
        total += w
        if w <= 0:
            reasons.append(
                f"{e.source_name}: evidenza scaduta (>{cfg['decay_days']}gg, "
                f"osservata il {e.observed_on}) — non conta per la corroborazione"
            )
        else:
            active_types.add(e.source_type)
            if e.source_type == SourceType.SOLD_COMP and e.marketplace:
                active_sold_marketplaces.add(e.marketplace)

    escalation_via_types = len(active_types) >= MIN_DISTINCT_SOURCES_TO_ESCALATE
    escalation_via_marketplaces = len(active_sold_marketplaces) >= MIN_INDEPENDENT_MARKETPLACES

    if escalation_via_types:
        pass  # ok, corroborazione da tipi di fonte diversi
    elif escalation_via_marketplaces:
        reasons.append(
            f"escalation sbloccata dalla regola B: {len(active_sold_marketplaces)} "
            f"marketplace indipendenti con vendite concluse "
            f"({', '.join(sorted(active_sold_marketplaces))}) — accettato anche senza "
            f"fonte ufficiale/community"
        )
    else:
        reasons.append(
            f"solo {len(active_types)} tipo/i di fonte attiva e "
            f"{len(active_sold_marketplaces)} marketplace indipendenti con vendite "
            f"concluse (< {MIN_INDEPENDENT_MARKETPLACES} richiesti) — non basta a "
            f"superare 'Bassa'"
        )
        total = min(total, BASSA_CEILING)

    total = min(total, MAX_SCORE)

    if total >= 70:
        band = BAND_ALTA
    elif total >= 40:
        band = BAND_MEDIA
    else:
        band = BAND_BASSA

    return ScoreResult(
        claim_id=claim_id,
        score=total,
        band=band,
        distinct_source_types=len(active_types),
        reasons=reasons,
        evidences=evidences,
    )


if __name__ == "__main__":
    # Demo con i due casi REALI discussi in questa sessione, come controllo di sanità.
    today = date(2026, 9, 9)

    print("=" * 70)
    print("CASO 1 — Teemo cinese FND-196/298: solo la vendita da 800$ di giugno")
    print("(questo è esattamente lo stato in cui eravamo prima del secondo giro")
    print(" di ricerca: un solo tipo di fonte, nessuna corroborazione)")
    print("=" * 70)
    teemo_thin = [
        Evidence(
            SourceType.SOLD_COMP,
            "eBay - vendita conclusa (New/Sealed)",
            date(2026, 6, 18),
            url="https://www.ebay.com/itm/278102406588",
            note="$800, condizione New",
        ),
    ]
    print(score_claim("teemo_fnd196_valore_alto", teemo_thin, as_of=today).summary())

    print()
    print("=" * 70)
    print("CASO 1b — stesso claim, MA con una seconda fonte indipendente")
    print("(es. se avessimo trovato conferma su un pop report o un articolo")
    print(" community che parla della stessa carta)")
    print("=" * 70)
    teemo_corroborated = teemo_thin + [
        Evidence(
            SourceType.COMMUNITY,
            "YGOrganization-style community article sulla scarsità del promo",
            date(2026, 7, 1),
            note="conferma indipendente della domanda/scarsità",
        ),
    ]
    print(score_claim("teemo_fnd196_valore_alto", teemo_corroborated, as_of=today).summary())

    print()
    print("=" * 70)
    print("CASO 1c — Teemo: regola B in azione. Niente fonte ufficiale/community,")
    print("ma 2 vendite concluse RECENTI su 2 marketplace diversi")
    print("=" * 70)
    teemo_two_marketplaces = [
        Evidence(
            SourceType.SOLD_COMP,
            "eBay - vendita conclusa",
            date(2026, 9, 1),
            marketplace="eBay",
            note="$780",
        ),
        Evidence(
            SourceType.SOLD_COMP,
            "Cardmarket - vendita conclusa",
            date(2026, 8, 25),
            marketplace="Cardmarket",
            note="€720",
        ),
    ]
    print(score_claim("teemo_fnd196_valore_alto", teemo_two_marketplaces, as_of=today).summary())

    print()
    print("=" * 70)
    print("CASO 2 — Prismatic Evolutions SPC: hype da lancio ben documentato")
    print("(prezzo eBay/TCGPlayer sopra MSRP in modo consistente, più fonte")
    print(" ufficiale sul MSRP originale)")
    print("=" * 70)
    spc = [
        Evidence(
            SourceType.SOLD_COMP,
            "eBay - vendita conclusa",
            date(2026, 9, 7),
            note="$240, in linea con decine di altre vendite recenti",
            marketplace="eBay",
        ),
        Evidence(
            SourceType.SOLD_COMP,
            "TCGPlayer - vendita conclusa",
            date(2026, 9, 5),
            note="$241",
            marketplace="TCGPlayer",
        ),
        Evidence(
            SourceType.OFFICIAL,
            "Pokemon.com - annuncio prodotto e MSRP",
            date(2025, 5, 16),
            note="MSRP originale ~$120",
        ),
    ]
    print(score_claim("prismatic_evo_spc_hype", spc, as_of=today).summary())

    print()
    print("=" * 70)
    print("CASO 3 — claim di un solo rivenditore su una tiratura dichiarata")
    print("(es. 'solo 5000 pezzi' letto su UNO shop, mai confermato altrove:")
    print(" esattamente il caso del Teemo che avevo etichettato male)")
    print("=" * 70)
    print_run_claim = [
        Evidence(
            SourceType.LISTING_CLAIM,
            "Mims Hobby Shop - descrizione prodotto",
            date(2026, 8, 1),
            note="'only 5,000 cards available globally' — non è una fonte primaria",
        ),
    ]
    print(score_claim("teemo_tiratura_5000", print_run_claim, as_of=today).summary())
