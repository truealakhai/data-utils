"""
konami_scanner.py — News ufficiali Konami Yu-Gi-Oh (yugioh-card.com/eu).

VERIFICATO: pagina raggiungibile senza protezione anti-bot (a differenza di
pokemon.com), struttura reale ispezionata oggi (non stimata come per
Serebii/PokeBeach). Esiste anche la versione italiana su /eu/it/.

Fonte OFFICIAL, non COMMUNITY: è direttamente il sito Konami, non un sito
di terzi che riporta la notizia — vale 40 punti nello scoring invece di 20,
e decade più lentamente (180gg).

Formato osservato di ogni voce (un singolo link che racchiude tutto):
"{Categoria} {D Month YYYY} {Titolo} {estratto…} More" — es.
"News 9 September 2026 Attention, Duelists! KONAMI Unveils... More"
Categorie osservate: News, Update, Link, Speed Duel.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable, List, Optional

from scoring import Evidence, SourceType
from keywords import GENERIC, YUGIOH, EXCLUDE

NEWS_URL = "https://www.yugioh-card.com/eu/news/"

# Specifico per Yu-Gi-Oh: generico + i termini che caratterizzano le carte
# di valore più alto per questo gioco (vedi keywords.py).
RELEVANT_KEYWORDS = GENERIC + YUGIOH

# Cattura: (categoria) (D Month YYYY) (resto: titolo+estratto, 'More' finale rimosso)
ENTRY_PATTERN = re.compile(
    r"(News|Update|Link|Speed Duel)\s+"
    r"(\d{1,2}\s+[A-Za-z]+\s+\d{4})\s+"
    r"(.+?)(?:\s+More)?$"
)


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


@dataclass
class KonamiNewsItem:
    category: str
    published_on: date
    title: str
    url: str


def _parse_date(raw: str) -> Optional[date]:
    try:
        return datetime.strptime(raw.strip(), "%d %B %Y").date()
    except ValueError:
        return None


def fetch_konami_news(http_get: Callable[[str], str] = default_http_get) -> List[KonamiNewsItem]:
    from bs4 import BeautifulSoup

    html = http_get(NEWS_URL)
    soup = BeautifulSoup(html, "html.parser")

    items = []
    for a in soup.find_all("a", href=True):
        text = a.get_text(" ", strip=True)
        m = ENTRY_PATTERN.match(text)
        if not m:
            continue
        category, raw_date, title = m.groups()
        parsed_date = _parse_date(raw_date)
        if parsed_date is None:
            continue
        items.append(KonamiNewsItem(
            category=category,
            published_on=parsed_date,
            title=title.strip(),
            url=a["href"],
        ))
    return items


def _is_relevant(item: KonamiNewsItem) -> bool:
    text = item.title.lower()
    if any(kw in text for kw in EXCLUDE):
        return False
    return any(kw in text for kw in RELEVANT_KEYWORDS)


def find_new_relevant_news(items: List[KonamiNewsItem], seen_urls: set) -> List[KonamiNewsItem]:
    new_ones = [i for i in items if i.url not in seen_urls]
    return [i for i in new_ones if _is_relevant(i)]


def news_to_evidence(item: KonamiNewsItem) -> Evidence:
    return Evidence(
        source_type=SourceType.OFFICIAL,
        source_name="Konami Yu-Gi-Oh EU - News ufficiali",
        observed_on=item.published_on,
        url=item.url,
        note=f"[{item.category}] {item.title}",
    )


if __name__ == "__main__":
    # Dati REALI osservati oggi sulla pagina (non inventati), riformattati
    # come li restituirebbe BeautifulSoup su un tag <a>.
    real_examples = [
        "News 9 September 2026 Attention, Duelists! KONAMI Unveils Yu‑Gi‑Oh! TAG FORCE GX, a Remake of the Beloved Yu‑Gi‑Oh! GX TAG FORCE 3! The Gates of Duel Academy re-open February 16, 2027 More",
        "News 23 July 2026 Card Correction Announcement for Chaos Origins Release Attention Duelists, During production of Chaos Origins... More",
        "Update 12 January 2026 Yu‑Gi‑Oh! DUEL LINKS CELEBRATES 9TH ANNIVERSARY Take part in a celebratory campaign where you can earn Red-Eyes Dark Dragoon and other special rewards More",
    ]
    urls = [
        "https://www.yugioh-card.com/eu/attention-duelists-konami-unveils-yu-gi-oh-tag-force-gx/",
        "https://www.yugioh-card.com/eu/card-correction-announcement-for-chaos-origins-release/",
        "https://www.yugioh-card.com/eu/duelists-unite-yu-gi-oh-duel-links-celebrates-9th-anniversary/",
    ]

    print("=" * 70)
    print("Verifica del pattern regex contro testo reale della pagina")
    print("=" * 70)
    for text, url in zip(real_examples, urls):
        m = ENTRY_PATTERN.match(text)
        if m:
            category, raw_date, title = m.groups()
            print(f"  OK  [{category}] {_parse_date(raw_date)} — {title[:60]}...")
        else:
            print(f"  FALLITO a interpretare: {text[:60]}...")
