"""
riftbound_official_scanner.py — News ufficiali Riftbound (playriftbound.com).

VERIFICATO: pagina raggiungibile senza protezione anti-bot, struttura reale
ispezionata oggi. Fonte OFFICIAL (è il sito Riot/publisher stesso, non un
terzo che ne parla) — 40 punti nello scoring, decadimento lento (180gg).

Formato osservato di ogni voce (un singolo link che racchiude tutto,
nessun separatore tra i pezzi):
"{Categoria}{ISO8601 timestamp}{Titolo}{estratto…}" — es.
"Announcements2026-09-04T16:00:00.000ZKorea's Rift Opens on September 18South Korea is getting ready for Riftbound."
Categorie osservate: Announcements, Organized Play, Rules and Releases.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable, List, Optional

from scoring import Evidence, SourceType

NEWS_URL = "https://playriftbound.com/en-us/news/"

RELEVANT_KEYWORDS = [
    "exclusive", "limited", "promo", "rare", "tournament", "prize",
    "sold out", "restock", "pre-order", "preorder", "drawing",
]

# Cattura: (tutto prima del timestamp = categoria) (timestamp ISO) (resto = titolo+estratto)
ENTRY_PATTERN = re.compile(
    r"^(.*?)(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z)(.+)$"
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
class RiftboundNewsItem:
    category: str
    published_on: date
    title_and_excerpt: str  # titolo ed estratto non sono separabili in modo affidabile dal testo grezzo
    url: str


def _parse_iso(raw: str) -> Optional[date]:
    try:
        return datetime.strptime(raw, "%Y-%m-%dT%H:%M:%S.%fZ").date()
    except ValueError:
        return None


def fetch_riftbound_news(http_get: Callable[[str], str] = default_http_get) -> List[RiftboundNewsItem]:
    from bs4 import BeautifulSoup

    html = http_get(NEWS_URL)
    soup = BeautifulSoup(html, "html.parser")

    items = []
    for a in soup.find_all("a", href=True):
        raw_text = a.get_text(strip=True)
        m = ENTRY_PATTERN.match(raw_text)
        if not m:
            continue
        category, raw_date, rest = m.groups()
        parsed_date = _parse_iso(raw_date)
        if parsed_date is None or not category:
            continue
        items.append(RiftboundNewsItem(
            category=category.strip(),
            published_on=parsed_date,
            title_and_excerpt=rest.strip(),
            url=a["href"],
        ))
    return items


def _is_relevant(item: RiftboundNewsItem) -> bool:
    text = item.title_and_excerpt.lower()
    return any(kw in text for kw in RELEVANT_KEYWORDS)


def find_new_relevant_news(items: List[RiftboundNewsItem], seen_urls: set) -> List[RiftboundNewsItem]:
    new_ones = [i for i in items if i.url not in seen_urls]
    return [i for i in new_ones if _is_relevant(i)]


def news_to_evidence(item: RiftboundNewsItem) -> Evidence:
    return Evidence(
        source_type=SourceType.OFFICIAL,
        source_name="Riot/PlayRiftbound.com - News ufficiali",
        observed_on=item.published_on,
        url=item.url,
        note=f"[{item.category}] {item.title_and_excerpt}",
    )


if __name__ == "__main__":
    # Dati REALI osservati oggi sulla pagina (non inventati).
    real_examples = [
        (
            "Announcements2026-09-04T16:00:00.000ZRiftbound Vendetta 2.0 Drawing FAQEverything you need to know about the second round of Vendetta drawings.",
            "https://playriftbound.com/en-us/news/announcements/product-drawing-faq/",
        ),
        (
            "Organized Play2026-08-10T16:00:00.000ZAll Eyes on BarcelonaSpain sees the first Vendetta Regional Qualifier kick off the new set's competitive season.",
            "https://playriftbound.com/en-us/news/organizedplay/all-eyes-on-barcelona",
        ),
    ]

    print("=" * 70)
    print("Verifica del pattern regex contro testo reale della pagina")
    print("=" * 70)
    for text, url in real_examples:
        m = ENTRY_PATTERN.match(text)
        if m:
            category, raw_date, rest = m.groups()
            print(f"  OK  [{category.strip()}] {_parse_iso(raw_date)} — {rest.strip()[:60]}...")
        else:
            print(f"  FALLITO a interpretare: {text[:60]}...")
