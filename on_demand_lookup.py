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
- ATTENZIONE: nei frammenti di ricerca su un'inserzione eBay, il numero che
  vedi accanto potrebbe essere il COSTO DI SPEDIZIONE, non il prezzo della
  carta — se non è chiaro quale sia quale, non riportarlo come prezzo di
  vendita. Apri/verifica la pagina reale prima di usare quel numero.
- Se trovi solo prezzi di richiesta, riportali comunque ma etichettali
  chiaramente come tali, non come vendite.
- Se una carta è nota per un identificatore preciso (codice set + numero,
  es. "FND-196"), prova quello ESPLICITAMENTE come query separata, non solo
  il nome descrittivo — i venditori (spesso internazionali) usano il codice
  in modo molto più coerente di descrizioni tradotte o generiche.
- Prova almeno 2-3 formulazioni diverse della ricerca prima di concludere che
  non c'è nulla — una singola query che non trova risultati non basta.
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


def _extract_json(raw_text: str) -> Optional[str]:
    """
    I modelli spesso restituiscono JSON avvolto in ```json ... ``` o con
    testo prima/dopo, anche quando il prompt chiede esplicitamente 'solo
    JSON' — comportamento comune, non specifico di questo caso. Prova, in
    ordine: (1) il testo così com'è, (2) dentro un blocco ```json o ```,
    (3) dal primo '{' all'ultimo '}' nel testo.
    """
    raw_text = raw_text.strip()

    try:
        json.loads(raw_text)
        return raw_text
    except json.JSONDecodeError:
        pass

    import re
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_text, re.DOTALL)
    if fence_match:
        candidate = fence_match.group(1)
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            pass

    first_brace = raw_text.find("{")
    last_brace = raw_text.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        candidate = raw_text[first_brace:last_brace + 1]
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            pass

    return None


def parse_response(raw_json: str) -> tuple[List[PriceResult], str]:
    """
    Parsing difensivo: se il modello non rispetta il formato (capita, non è
    garantito), non crasha tutto il bot — ritorna lista vuota + messaggio di
    errore comprensibile invece di un'eccezione che il bot Telegram non sa
    gestire a metà conversazione con l'utente.
    """
    extracted = _extract_json(raw_json)
    if extracted is None:
        return [], "Non sono riuscito a interpretare la risposta della ricerca. Riprova."

    data = json.loads(extracted)

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
    ebay_http_get=None,
) -> str:
    """
    Funzione principale da collegare al comando Telegram. Ritorna il testo
    già pronto da mandare in risposta all'utente.

    ebay_http_get: se fornito, interroga PRIMA il filtro "Venduti" di eBay
    direttamente (ebay_sold_scanner.py) — dati reali, non mediati da una
    ricerca web generica che spesso non li trova (scoperto insieme
    all'utente confrontando i risultati). Se None, salta questo passaggio
    e si affida solo alla ricerca di Claude, come prima.
    """
    ebay_evidences = []
    if ebay_http_get is not None:
        try:
            from ebay_sold_scanner import fetch_sold_listings, listing_to_evidence
            listings = fetch_sold_listings(product_query, tld="it", http_get=ebay_http_get)
            ebay_evidences = [listing_to_evidence(l) for l in listings if l.price > 0]
        except Exception as e:
            print(f"  [info] eBay diretto non disponibile ({e}), procedo solo con la ricerca Claude")

    raw = client.search_product_prices(
        query=product_query,
        days_back=days_back,
    )
    results, summary = parse_response(raw)
    claude_evidences = results_to_evidences(results)

    # Deduplica per URL: se Claude ha trovato la STESSA inserzione che
    # abbiamo già da eBay diretto, non contarla due volte.
    seen_urls = {e.url for e in ebay_evidences}
    evidences = ebay_evidences + [e for e in claude_evidences if e.url not in seen_urls]

    if not evidences:
        return f"🔍 {product_query}\n\n{summary or 'Nessuna vendita conclusa verificabile trovata negli ultimi ' + str(days_back) + ' giorni.'}"

    claim_id = claim_id or product_query.lower().replace(" ", "_")
    score = score_claim(claim_id, evidences, as_of=date.today())

    lines = [f"🔍 {product_query}", ""]
    if ebay_evidences:
        lines.append(f"({len(ebay_evidences)} vendite trovate direttamente su eBay)")
    lines.append(summary or "")
    lines.append("")
    lines.append(f"Affidabilità: {score.band} ({score.score:.0f}/100)")
    lines.append("")
    for ev in evidences:
        tag = "✅ venduto" if ev.source_type == SourceType.SOLD_COMP else "💬 richiesta"
        lines.append(f"{tag} — {ev.note} ({ev.observed_on}) — {ev.url}")

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

    print()
    print("=" * 70)
    print("Combinazione: eBay diretto (dati REALI dai tuoi screenshot) + Claude")
    print("=" * 70)

    def fake_ebay_http(url: str) -> str:
        # HTML minimale nel formato li.s-item, con i valori REALI che hai mandato
        return """<html><body>
        <li class="s-item">
          <a class="s-item__link" href="https://www.ebay.it/itm/aaa"></a>
          <div class="s-item__title">2025 RIFTBOUND LEAGUE OF LEGENDS CARTA EVENTO CAPODANNO CINESE TEEMO</div>
          <span class="s-item__price">EUR 2.928,01</span>
          <span class="s-item__caption">23 ago 2026</span>
        </li>
        <li class="s-item">
          <a class="s-item__link" href="https://www.ebay.it/itm/bbb"></a>
          <div class="s-item__title">League of Legends Gioco di Carte Arcano Cinese LOL Riftbound Teemo FND.196/298Promo</div>
          <span class="s-item__price">US $459.99</span>
          <span class="s-item__caption">19 ago 2026</span>
        </li>
        </body></html>"""

    response3 = query_product(client, "Riftbound Teemo capodanno", days_back=90, ebay_http_get=fake_ebay_http)
    print(response3)
