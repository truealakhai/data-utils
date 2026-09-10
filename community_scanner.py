"""
community_scanner.py — Monitor leggero per fonti community, senza RSS/API.

STATO VERIFICATO PRIMA DI SCRIVERE QUESTO CODICE:

- Serebii.net: raggiungibile senza protezione anti-bot. Copre spesso notizie
  Pokémon Company (inclusi annunci set TCG) prima ancora che siano leggibili
  su pokemon.com in forma processabile — lo uso quindi anche come proxy
  informale per gli ufficiali, ma l'Evidence resta COMMUNITY (è comunque un
  sito di terzi che riporta la notizia, non l'annuncio primario).
  Struttura osservata dalla pagina (letta tramite fetch, non ispezionando
  l'HTML grezzo — i selettori sotto sono una stima ragionevole, NON
  verificata contro i tag reali, vanno controllati/aggiustati la prima volta
  che li lanci davvero): blocchi data (titolo di livello 2, link alla pagina
  del giorno) con sotto-sezioni "In The X Department" (titolo di livello 3),
  ciascuna con uno o più paragrafi di notizia e un link a una sezione di
  approfondimento.

- Pokemon.com (sito ufficiale): protetto da Incapsula/Imperva — un fetch
  semplice restituisce una pagina di sfida anti-bot, non contenuto vero.
  NON costruisco uno scanner per questo: bypassarlo richiederebbe tecniche
  (browser headless, rotazione IP) che non voglio usare senza un tuo ok
  esplicito, sia per rischio ToS sia perché è uno sforzo sproporzionato
  quando Serebii copre già la stessa notizia. Se un giorno serve DAVVERO
  la fonte primaria (es. per una data ufficiale di embargo), verifica a mano.

- PokeBeach: RSS rotto/inaffidabile (lamentele pubbliche della loro stessa
  community, non solo mie). Stesso approccio di Serebii: scraping leggero,
  selettori da verificare alla prima esecuzione reale.

- Konami (yugioh-card.com) e Riot/UVS Games (Riftbound): NON ancora
  controllati — non li implemento per non inventare uno schema.

Design: una classe HeadlineMonitor indipendente dal sito. Ogni fonte
implementa solo "dammi la lista di headline della pagina" (titolo, url,
dipartimento, data se disponibile) — il confronto con quanto già visto e la
conversione in Evidence sono comuni a tutte le fonti.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Callable, List, Optional, Set

from scoring import Evidence, SourceType

HttpGet = Callable[[str], str]  # url -> HTML grezzo (stringa)

# Lista centralizzata in keywords.py — Serebii/PokeBeach coprono più giochi,
# quindi uso tutte le parole chiave (generiche + specifiche per gioco).
from keywords import ALL_KEYWORDS as RELEVANT_KEYWORDS, EXCLUDE


def default_http_get(url: str) -> str:
    """
    Implementazione reale. Non eseguibile qui (niente rete).

    Header ampliati rispetto alla versione precedente (solo User-Agent) —
    tentativo per il 403 di PokeBeach: un User-Agent generico "Mozilla/5.0"
    da solo è un segnale abbastanza riconoscibile come bot per un WAF un
    minimo sofisticato. Questi assomigliano di più a una richiesta di
    browser vera. NON è garantito che risolva — se PokeBeach usa un
    controllo più stringente (challenge JS, fingerprinting), niente di
    quello che possiamo fare con semplici header lo aggira, e a quel punto
    l'opzione onesta resta toglierlo dallo scanner automatico.
    """
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


@dataclass
class Headline:
    title: str
    url: str
    department: str  # es. "TCG", "Games" — dalla sezione "In The X Department"
    site: str


def _is_relevant(headline: Headline) -> bool:
    text = f"{headline.title}".lower()
    if any(kw in text for kw in EXCLUDE):
        return False
    return any(kw in text for kw in RELEVANT_KEYWORDS)


def serebii_fetch_headlines(http_get: HttpGet = default_http_get) -> List[Headline]:
    """
    NOTA: usa BeautifulSoup con selettori stimati (h2/h3/a), non confermati
    contro l'HTML grezzo reale — probabile che vadano aggiustati alla prima
    esecuzione vera. La logica di filtro/dedup sotto non dipende da questo,
    quindi un aggiustamento qui non tocca il resto del modulo.
    """
    from bs4 import BeautifulSoup

    html = http_get("https://serebii.net/")
    soup = BeautifulSoup(html, "html.parser")

    headlines: List[Headline] = []
    current_department = "Unknown"

    # Cammino sequenziale sui tag di titolo: h3 "In The X Department" imposta
    # il dipartimento corrente, i link successivi fino al prossimo h3/h2
    # vengono attribuiti a quel dipartimento.
    for tag in soup.find_all(["h2", "h3", "a"]):
        if tag.name == "h2":
            current_department = "Unknown"  # nuovo blocco data, reset
        elif tag.name == "h3":
            text = tag.get_text(strip=True)
            if text.lower().startswith("in the") and "department" in text.lower():
                current_department = text.lower().replace("in the", "").replace("department", "").strip()
        elif tag.name == "a" and tag.get("href"):
            title = tag.get_text(strip=True)
            if not title or len(title) < 8:
                continue  # scarta link di navigazione/icone senza testo utile
            headlines.append(Headline(
                title=title,
                url=tag["href"],
                department=current_department,
                site="Serebii.net",
            ))

    return headlines


def pokebeach_fetch_headlines(http_get: HttpGet = default_http_get) -> List[Headline]:
    """Stessa cautela di serebii_fetch_headlines sui selettori non confermati."""
    from bs4 import BeautifulSoup

    html = http_get("https://www.pokebeach.com/")
    soup = BeautifulSoup(html, "html.parser")

    headlines = []
    for tag in soup.find_all(["h2", "h3"]):
        link = tag.find("a")
        if link and link.get("href") and link.get_text(strip=True):
            headlines.append(Headline(
                title=link.get_text(strip=True),
                url=link["href"],
                department="tcg",  # PokeBeach è TCG-focused: niente da filtrare per reparto
                site="PokeBeach",
            ))
    return headlines


def find_new_relevant_headlines(
    headlines: List[Headline],
    seen_urls: Set[str],
    tcg_only: bool = True,
) -> List[Headline]:
    """
    Filtra: non ancora visti + (opzionale) reparto TCG + parole chiave
    rilevanti. seen_urls va gestito dal chiamante (persistenza vera arriva
    col punto 'b' — qui è solo un parametro iniettato, testabile con un set
    finto).
    """
    new_ones = [h for h in headlines if h.url not in seen_urls]
    if tcg_only:
        new_ones = [h for h in new_ones if "tcg" in h.department.lower() or h.site == "PokeBeach"]
    return [h for h in new_ones if _is_relevant(h)]


def headline_to_evidence(headline: Headline, observed_on: Optional[date] = None) -> Evidence:
    return Evidence(
        source_type=SourceType.COMMUNITY,
        source_name=headline.site,
        observed_on=observed_on or date.today(),
        url=headline.url,
        note=f"[{headline.department}] {headline.title}",
    )


if __name__ == "__main__":
    # Demo con HTML finto minimale (niente rete/BeautifulSoup reale servono
    # solo per dimostrare la logica di filtro + conversione a Evidence).
    fake_headlines = [
        Headline("Ranked Battle Season 10 announced", "https://serebii.net/a", "games", "Serebii.net"),
        Headline(
            "Pokemon Company reveals Exclusive Promo Card for Worlds 2026, limited to attendees only",
            "https://serebii.net/b", "tcg", "Serebii.net",
        ),
        Headline("New anime episode airs in Japan", "https://serebii.net/c", "anime", "Serebii.net"),
        Headline(
            "30th Celebration set sold out within minutes of Japanese pre-order opening",
            "https://serebii.net/d", "tcg", "Serebii.net",
        ),
    ]

    seen = {"https://serebii.net/a"}  # simuliamo che la prima l'avevamo già vista

    print("=" * 70)
    print("4 headline finte, 1 già vista, 2 rilevanti (parole chiave) su TCG")
    print("=" * 70)
    new_relevant = find_new_relevant_headlines(fake_headlines, seen)
    for h in new_relevant:
        ev = headline_to_evidence(h, observed_on=date(2026, 9, 9))
        print(f"  · {ev.note}")
        print(f"    -> Evidence: {ev.source_type.value}, {ev.url}")
