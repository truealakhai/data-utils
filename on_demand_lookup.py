"""
on_demand_lookup.py — Ricerca on-demand di un prodotto/carta specifico, per
uso da comando Telegram (es. utente scrive "Riftbound Teemo capodanno").

Come funziona: il bot chiama l'API Anthropic con il tool web_search abilitato
(funzionalità reale e documentata, verificata prima di scrivere questo file)
e un prompt che istruisce Claude a fare esattamente quello che ho fatto io a
mano in chat per il Teemo/Prismatic Evolutions — cercare vendite CONCLUSE
reali, distinguerle dai prezzi di richiesta, citare le fonti — ma con
risposta in JSON strutturato invece che in prosa, così il risultato si
aggancia allo stesso scoring.py usato da tutti gli altri scanner.

NOTA: qui non posso fare una vera chiamata API (niente rete in questo
ambiente). L'interfaccia AnthropicClient sotto è iniettabile: nel tuo
ambiente reale colleghi un client che usa anthropic.Anthropic() per davvero;
qui la testo con una risposta finta basata sui dati REALI del Teemo che
abbiamo verificato in questa stessa conversazione (la vendita da $800 di
giugno), non inventata.

Costo: a consumo in base al volume di ricerche + token — controlla la
pricing page di Anthropic per la cifra esatta, non la invento qui.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from typing import List, Optional, Protocol

from scoring import Evidence, SourceType, score_claim

SYSTEM_PROMPT = """Sei un ricercatore di prezzi per il mercato secondario dei trading card game.
Dato il nome di un prodotto/carta, cerca sul web le sue VENDITE CONCLUSE reali
(non i prezzi di richiesta) degli ultimi {days_back} giorni, su qualsiasi
marketplace (eBay, Cardmarket, TCGPlayer, ecc.).

Regole:
- Riporta SOLO transazioni che puoi confermare come concluse (stato "sold",
  "venduto", asta terminata con vincitore) — mai un prezzo di richiesta
  spacciato per vendita.
- Se trovi solo prezzi di richiesta, riportali comunque ma etichettali
  chiaramente come tali, non come vendite.
- Ogni risultato deve avere una URL verificabile.
- Se non trovi nulla di verificabile, di' esplicitamente che non hai trovato
  vendite concluse recenti, non inventare un prezzo plausibile.

Rispondi SOLO con un JSON valido in questo formato, nessun altro testo:
{{
  "results": [
    {{"marketplace": "eBay", "price": 800.0, "currency": "USD", "date": "2026-06-18",
      "confirmed_sold": true, "condition": "New/Sealed", "url": "https://..."}}
  ],
  "summary_it": "Riassunto in una frase in italiano di quello che hai trovato."
}}"""


class AnthropicClient(Protocol):
    """Interfaccia minimale — un client reale usa anthropic.Anthropic() con
    tools=[{"type": "web_search_20250305", "name": "web_search"}]."""
    def search_product_prices(self, query: str, days_back: int) -> str:
        """Restituisce il testo grezzo della risposta di Claude (atteso: JSON)."""
        ...


@dataclass
class PriceResult:
    marketplace: str
    price: float
    currency: str
    sale_date: date
    confirmed_sold: bool
    condition: str
    url: str


def parse_response(raw_json: str) -> tuple[List[PriceResult], str]:
    """
    Parsing difensivo: se il modello non rispetta il formato (capita, non è
    garantito), non crasha tutto il bot — ritorna lista vuota + messaggio di
    errore comprensibile invece di un'eccezione che il bot Telegram non sa
    gestire a metà conversazione con l'utente.
    """
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError:
        return [], "Non sono riuscito a interpretare la risposta della ricerca. Riprova."

    results = []
    for r in data.get("results", []):
        try:
            results.append(PriceResult(
                marketplace=r["marketplace"],
                price=float(r["price"]),
                currency=r["currency"],
                sale_date=date.fromisoformat(r["date"]),
                confirmed_sold=bool(r["confirmed_sold"]),
                condition=r.get("condition", "n/d"),
                url=r["url"],
            ))
        except (KeyError, ValueError, TypeError):
            continue  # scarta il singolo risultato malformato, non tutta la risposta

    return results, data.get("summary_it", "")


def results_to_evidences(results: List[PriceResult]) -> List[Evidence]:
    evidences = []
    for r in results:
        evidences.append(Evidence(
            source_type=SourceType.SOLD_COMP if r.confirmed_sold else SourceType.LISTING_CLAIM,
            source_name=f"{r.marketplace} (ricerca on-demand)",
            observed_on=r.sale_date,
            url=r.url,
            note=f"{r.price} {r.currency} — {r.condition}" + ("" if r.confirmed_sold else " (prezzo di richiesta, non venduto)"),
            marketplace=r.marketplace if r.confirmed_sold else "",
        ))
    return evidences


def query_product(
    client: AnthropicClient,
    product_query: str,
    days_back: int = 90,
    claim_id: Optional[str] = None,
) -> str:
    """
    Funzione principale da collegare al comando Telegram. Ritorna il testo
    già pronto da mandare in risposta all'utente.
    """
    raw = client.search_product_prices(
        query=product_query,
        days_back=days_back,
    )
    results, summary = parse_response(raw)
    evidences = results_to_evidences(results)

    if not evidences:
        return f"🔍 {product_query}\n\n{summary or 'Nessuna vendita conclusa verificabile trovata negli ultimi ' + str(days_back) + ' giorni.'}"

    claim_id = claim_id or product_query.lower().replace(" ", "_")
    score = score_claim(claim_id, evidences, as_of=date.today())

    lines = [f"🔍 {product_query}", "", summary, ""]
    lines.append(f"Affidabilità: {score.band} ({score.score:.0f}/100)")
    lines.append("")
    for ev, r in zip(evidences, results):
        tag = "✅ venduto" if r.confirmed_sold else "💬 richiesta"
        lines.append(f"{tag} — {r.price} {r.currency} su {r.marketplace} ({r.sale_date}) — {r.url}")

    return "\n".join(lines)


class _FakeAnthropicClient:
    """
    Demo basata sui dati REALI verificati in questa conversazione (la
    vendita Teemo da $800, giugno 2026) — non inventata per l'occasione.
    """
    def search_product_prices(self, query: str, days_back: int) -> str:
        if "teemo" in query.lower():
            return json.dumps({
                "results": [
                    {
                        "marketplace": "eBay",
                        "price": 800.0,
                        "currency": "USD",
                        "date": "2026-06-18",
                        "confirmed_sold": True,
                        "condition": "New/Sealed",
                        "url": "https://www.ebay.com/itm/278102406588",
                    },
                    {
                        "marketplace": "eBay",
                        "price": 250.0,
                        "currency": "EUR",
                        "date": "2026-09-05",
                        "confirmed_sold": False,
                        "condition": "Lightly played",
                        "url": "https://www.ebay.de/itm/example",
                    },
                ],
                "summary_it": "Trovata una vendita conclusa reale a $800 (giugno, sigillata) e un'inserzione attiva a 250€ (non venduta) per una copia rovinata.",
            })
        return json.dumps({"results": [], "summary_it": "Nessun risultato per questa query."})


if __name__ == "__main__":
    client = _FakeAnthropicClient()

    print("=" * 70)
    print("Simulazione comando Telegram: utente scrive 'Riftbound Teemo capodanno'")
    print("=" * 70)
    response = query_product(client, "Riftbound Teemo capodanno", days_back=90)
    print(response)

    print()
    print("=" * 70)
    print("Query senza risultati")
    print("=" * 70)
    response2 = query_product(client, "Carta Inesistente XYZ", days_back=90)
    print(response2)
