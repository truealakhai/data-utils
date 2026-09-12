"""
watchlist.py — I prodotti da monitorare. Questo è il file che modifichi
quando vuoi aggiungere/togliere un prodotto — l'orchestratore (orchestrator.py)
non va toccato per questo.

Ristretta di proposito (decisione presa in sessione): non "tutto il mercato
TCG", ma una lista esplicita — è quello che rende gli alert affidabili
invece che rumore.

Campi per voce:
- claim_id: identificatore univoco, usato per lo stato persistito e gli alert
- game: "pokemon" | "yugioh" | "riftbound" | "wow" (wow non ha scanner
  automatici, resta fuori da questa lista — verifica manuale, come deciso)
- query: il nome/termine di ricerca da passare agli scanner
- sources: quali scanner interrogare per questa voce — deve corrispondere
  alle chiavi in orchestrator.PER_PRODUCT_ADAPTERS più "community"/"reddit"
- cardmarket_id: SOLO per Pokémon, l'ID carta tcgdex (es. "swsh1-1")
- riftbound_api_keys: SOLO per Riftbound, popolato da main.py con le chiavi
  vere lette dalle variabili d'ambiente — non scrivere chiavi qui dentro

Campi opzionali SOLO per la fonte "ebay_new_listings" (adapter_ebay_new_listings
in orchestrator.py, vedi ebay_new_listing_scanner.py):
- ebay_queries: lista di varianti di query da cercare su eBay (nomi IT/EN,
  abbreviazioni) — i risultati vengono uniti e deduplicati per item_id. Se
  assente, si usa semplicemente [query]. NON sostituisce "query", che resta
  usato per lo smistamento delle fonti "a spazzolata" (community/reddit) —
  tenerli separati permette a "query" di restare generico (buono per
  intercettare hype nelle notizie) mentre "ebay_queries" può essere
  specifico per prodotto (buono per non mischiare varianti diverse dello
  stesso set, es. ETB vs Ultra Premium Collection).
- ebay_include_any_of: lista di gruppi di sinonimi — per ogni gruppo deve
  comparire ALMENO un termine nel titolo (AND fra i gruppi, OR dentro al
  gruppo). Filtro anti-falsi-positivi, si somma a EXCLUDE/EBAY_LISTING_EXCLUDE
  di keywords.py.
- ebay_exclude: termini di esclusione aggiuntivi SOLO per questo prodotto
  (oltre a EXCLUDE + EBAY_LISTING_EXCLUDE già globali) — es. per non
  mischiare due varianti simili dello stesso set (Giorno/Notte, ecc.)
"""

WATCHLIST = [
    {
        "claim_id": "grookey_swsh1_1_hype",
        "game": "pokemon",
        "query": "Grookey",
        "cardmarket_id": "swsh1-1",
        "sources": ["cardmarket", "community", "reddit"],
    },
    {
        "claim_id": "jinx_riftbound_prezzo",
        "game": "riftbound",
        "query": "Jinx",
        "riftbound_api_keys": {},  # popolato da main.py da env
        "sources": ["riftbound", "ebay_new_listings", "riftbound_official"],
    },
    {
        "claim_id": "blue_eyes_white_dragon",
        "game": "yugioh",
        "query": "Blue-Eyes White Dragon",
        "sources": ["yugioh", "reddit", "konami", "ygorganization"],
    },
    {
        "claim_id": "teemo_fnd196_rarity",
        "game": "riftbound",
        "query": "Riftbound Teemo FND 196",
        "sources": ["ebay_new_listings"],  # Rarity Radar: nuove inserzioni, non hype di prezzo
    },
    # Le tre voci sotto erano un'unica "pokemon_30th_celebration_launch".
    # Separate in sessione per poter applicare ebay_include_any_of/
    # ebay_exclude in modo mirato: con un solo claim, "le 3 col prezzo più
    # basso" avrebbero sempre mostrato solo ETB (strutturalmente più
    # economico), nascondendo le UPC Giorno/Notte — che così restano
    # confrontate solo contro se stesse. "query" resta lo stesso per tutte
    # e tre (serve solo allo smistamento community/reddit, che ragiona per
    # hype sul lancio del set intero, non per singolo prodotto).
    #
    # NIENTE "cardmarket" su nessuna delle tre: il set esce il 16/09/2026,
    # tcgdex non ha ancora un card_id/prezzo per queste carte (verificato —
    # un tracker di settore segna esplicitamente "No price yet" su ogni
    # carta). Aggiungere "cardmarket" con un card_id reale tra 2-3
    # settimane, quando ci sarà storico Cardmarket vero.
    {
        "claim_id": "pokemon_30th_etb_launch",
        "game": "pokemon",
        "query": "30th Celebration",
        "sources": ["community", "reddit", "ebay_new_listings"],
        "ebay_queries": [
            "Pokemon 30th Celebration Elite Trainer Box",
            "Pokemon Set Allenatore Fuoriclasse 30 Anniversario",
        ],
        "ebay_include_any_of": [
            ["elite trainer box", "etb", "allenatore fuoriclasse"],
            ["30th", "30°", "30 anniversario", "celebration"],
        ],
        "ebay_exclude": ["scarlet violet", "sword shield", "sun moon"],
    },
    {
        "claim_id": "pokemon_30th_upc_day_launch",
        "game": "pokemon",
        "query": "30th Celebration",
        "sources": ["community", "reddit", "ebay_new_listings"],
        "ebay_queries": [
            "Pokemon 30th Celebration Ultra Premium Collection Day Espeon",
            "Pokemon 30 Anniversario Ultra Premium Giorno Espeon",
        ],
        "ebay_include_any_of": [
            ["ultra premium", "upc"],
            ["day", "giorno", "espeon"],
        ],
        # esclude anche la variante Notte, per non mischiare le due UPC
        "ebay_exclude": ["scarlet violet", "sword shield", "sun moon", "umbreon", "notte", "night"],
    },
    {
        "claim_id": "pokemon_30th_upc_night_launch",
        "game": "pokemon",
        "query": "30th Celebration",
        "sources": ["community", "reddit", "ebay_new_listings"],
        "ebay_queries": [
            "Pokemon 30th Celebration Ultra Premium Collection Night Umbreon",
            "Pokemon 30 Anniversario Ultra Premium Notte Umbreon",
        ],
        "ebay_include_any_of": [
            ["ultra premium", "upc"],
            ["night", "notte", "umbreon"],
        ],
        # esclude anche la variante Giorno, per non mischiare le due UPC
        "ebay_exclude": ["scarlet violet", "sword shield", "sun moon", "espeon", "giorno", "day"],
    },
]
