"""
keywords.py — Parole chiave condivise da tutti gli scanner "a spazzolata"
(community, reddit, konami, riftbound_official). Prima erano duplicate in
4 file diversi — centralizzate qui per evitare che finiscano scollegate
tra loro nel tempo.

GENERIC: si applica a qualunque gioco — termini di scarsità/hype generali.

Le liste per gioco sono state costruite cercando oggi cosa caratterizza
DAVVERO le carte/prodotti più costosi di ciascun gioco (non a memoria) —
fonti: guide di settore aggiornate al 2026 per Pokémon e Yu-Gi-Oh, pagina
news ufficiale per Riftbound (dato che è troppo giovane per avere guide di
settore consolidate).
"""

GENERIC = [
    "exclusive", "esclusiv", "limited", "limitat", "promo", "rare", "rar",
    "tournament", "torneo", "prize", "premio", "sold out", "esaurit",
    "restock", "pre-order", "preorder", "prevendita", "hype",
]

# Pokémon: termini che nelle guide 2026 caratterizzano sistematicamente le
# carte più costose — non semplici sinonimi di "raro", ma le categorie
# specifiche che il mercato paga di più.
POKEMON = [
    "special illustration rare", "sir", "alt art", "alternate art",
    "hyper rare", "secret rare", "gold star", "master ball",
    "trophy", "god pack", "1st edition", "shadowless", "rainbow rare",
    "futuristic rare", "corocoro", "full art",
]

# Yu-Gi-Oh: stesso criterio — le rarità/categorie che dominano le classifiche
# dei prezzi più alti, non l'elenco completo delle rarità del gioco.
YUGIOH = [
    "ghost rare", "starlight rare", "quarter century", "qcsr",
    "ultimate rare", "prize card", "shonen jump", "world championship",
    "1st edition", "short print", "stainless steel",
]

# Riftbound: gioco troppo giovane per guide di settore consolidate — termini
# presi dalla pagina news ufficiale stessa (drawing/lottery per gli
# esclusivi, "signature edition" per le varianti da campione).
RIFTBOUND = [
    "signature edition", "drawing", "secret garden", "alternate art",
    "regional championship", "worlds champion", "world championship",
]

ALL_KEYWORDS = GENERIC + POKEMON + YUGIOH + RIFTBOUND
