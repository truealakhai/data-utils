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
    {
        "claim_id": "pokemon_30th_celebration_launch",
        "game": "pokemon",
        "query": "30th Celebration",
        # NIENTE "cardmarket": il set esce il 16/09/2026, tcgdex non ha
        # ancora un card_id/prezzo per queste carte (verificato — un
        # tracker di settore segna esplicitamente "No price yet" su ogni
        # carta). Solo fonti a spazzolata per ora, per intercettare l'hype
        # del lancio. Aggiungere "cardmarket" con un card_id reale tra
        # 2-3 settimane, quando ci sarà storico Cardmarket vero.
        "sources": ["community", "reddit"],
    },
]
