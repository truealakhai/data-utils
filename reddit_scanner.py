"""
reddit_scanner.py — Monitor subreddit TCG per segnali di hype/scarsità.

DA SAPERE PRIMA DI USARLO (correzione rispetto a quanto detto a voce prima):
Reddit resta gratuito per uso non commerciale (100 richieste/minuto), ma da
fine 2025 ("Responsible Builder Policy") la registrazione app non è più
istantanea — ogni nuova app, anche gratuita, passa da un'approvazione
manuale con tempi non garantiti. Conviene fare la richiesta subito
(reddit.com/prefs/apps) perché il resto del modulo non serve a niente senza.

Uso PRAW (libreria standard) dietro un'interfaccia minimale (RedditClient)
così il modulo è testabile qui senza PRAW installato e senza rete — chi la
implementa per davvero collega semplicemente un wrapper PRAW a questa
interfaccia.

Sottoreddit di partenza suggeriti (da confermare/aggiustare con l'uso):
r/PokemonTCG, r/yugioh, r/RiftboundTCG. Non includo r/wow o simili: essendo
un gioco chiuso dal 2013, l'attività su Reddit specifica sul TCG è minima e
il segnale sarebbe quasi tutto rumore.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Callable, List, Optional, Protocol, Set

from scoring import Evidence, SourceType

DEFAULT_SUBREDDITS = ["PokemonTCG", "yugioh", "RiftboundTCG"]

RELEVANT_KEYWORDS = [
    "exclusive", "esclusiv", "limited", "limitat", "promo", "rare", "rar",
    "tournament", "torneo", "prize", "premio", "sold out", "esaurit",
    "restock", "pre-order", "preorder", "prevendita", "hype",
]


@dataclass
class RedditPost:
    post_id: str
    title: str
    url: str
    subreddit: str
    created_utc: float
    score: int          # upvote count — usato come filtro di rilevanza minima
    num_comments: int


class RedditClient(Protocol):
    """Interfaccia minimale: un vero wrapper PRAW implementa questo metodo."""
    def search_subreddit(self, subreddit: str, query: str, limit: int) -> List[RedditPost]:
        ...


def _is_relevant(post: RedditPost, min_score: int = 5) -> bool:
    text = post.title.lower()
    return post.score >= min_score and any(kw in text for kw in RELEVANT_KEYWORDS)


def scan_subreddits(
    client: RedditClient,
    query: str,
    subreddits: List[str] = None,
    limit_per_sub: int = 25,
) -> List[RedditPost]:
    subreddits = subreddits or DEFAULT_SUBREDDITS
    posts = []
    for sub in subreddits:
        posts += client.search_subreddit(sub, query, limit_per_sub)
    return posts


def find_new_relevant_posts(
    posts: List[RedditPost],
    seen_post_ids: Set[str],
    min_score: int = 5,
) -> List[RedditPost]:
    """seen_post_ids va gestito dal chiamante — persistenza vera nel punto 'b'."""
    new_ones = [p for p in posts if p.post_id not in seen_post_ids]
    return [p for p in new_ones if _is_relevant(p, min_score)]


def post_to_evidence(post: RedditPost) -> Evidence:
    observed_on = datetime.fromtimestamp(post.created_utc, tz=timezone.utc).date()
    return Evidence(
        source_type=SourceType.COMMUNITY,
        source_name=f"r/{post.subreddit}",
        observed_on=observed_on,
        url=post.url,
        note=f"'{post.title}' ({post.score} upvote, {post.num_comments} commenti)",
    )


class _FakeRedditClient:
    """Solo per la demo sotto — un vero client collegherebbe PRAW."""
    def search_subreddit(self, subreddit: str, query: str, limit: int) -> List[RedditPost]:
        if subreddit == "RiftboundTCG":
            return [
                RedditPost(
                    "abc123",
                    "PSA just confirmed the Chinese New Year Teemo promo is limited to 5000 worldwide - official statement",
                    "https://reddit.com/r/RiftboundTCG/abc123",
                    "RiftboundTCG",
                    created_utc=datetime(2026, 9, 8, tzinfo=timezone.utc).timestamp(),
                    score=340,
                    num_comments=88,
                ),
                RedditPost(
                    "def456",
                    "Just pulled a cool holo, nothing special",
                    "https://reddit.com/r/RiftboundTCG/def456",
                    "RiftboundTCG",
                    created_utc=datetime(2026, 9, 8, tzinfo=timezone.utc).timestamp(),
                    score=12,
                    num_comments=3,
                ),
            ]
        return []


if __name__ == "__main__":
    client = _FakeRedditClient()
    posts = scan_subreddits(client, query="Teemo", subreddits=["RiftboundTCG"])

    print("=" * 70)
    print("2 post trovati, 1 rilevante (parole chiave + soglia upvote),")
    print("l'altro è un pull normale senza segnale utile")
    print("=" * 70)
    new_relevant = find_new_relevant_posts(posts, seen_post_ids=set())
    for p in new_relevant:
        ev = post_to_evidence(p)
        print(f"  · {ev.note}")
        print(f"    -> Evidence: {ev.source_type.value}, osservata il {ev.observed_on}")

    print()
    print("=" * 70)
    print("Nota: questo post cita 'official statement' — se fosse vero,")
    print("andrebbe verificata la fonte primaria e magari alzata a OFFICIAL")
    print("a mano; un post Reddit che CITA un ufficiale resta COMMUNITY finché")
    print("non troviamo l'annuncio originale.")
    print("=" * 70)
    result_check = [ev for ev in [post_to_evidence(p) for p in new_relevant]]
    from scoring import score_claim
    result = score_claim("teemo_tiratura_5000_reddit", result_check, as_of=date(2026, 9, 9))
    print(result.summary())
