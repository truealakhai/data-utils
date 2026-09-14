"""
stock_watchlist.py — Prodotti specifici e i rivenditori dove controllarne
lo stock. A differenza di watchlist.py (giochi/query per gli scanner di
prezzo/hype), qui ogni voce è un prodotto preciso con URL espliciti — va
popolata a mano quando Discovery segnala qualcosa che merita monitoraggio
stock attivo (vedi stock_monitor.py per il perché).

Popolata oggi con gli URL reali verificati durante la sessione sul caso
Pokémon 30° Anniversario Ultra Premium Collection.
"""

STOCK_WATCHLIST = [
    {
        "product_id": "30th_celebration_upc_day",
        "product_name": "Pokémon 30° Anniversario UPC Giorno (Espeon)",
        "retailers": [
            {"name": "NerdStoreItalia", "url": "https://www.nerdstoreitalia.it/prodotto/pokemon-30-anniversario-espeon-collezione-ultra-premium-ita/"},
            {"name": "strategia2.it", "url": "https://www.strategia2.it/negozio/pokemon-30-anniversario-collezione-ultra-premium-espeon-ex/"},
            {"name": "nickeilashop", "url": "https://nickeilashop.com/products/pokemon-collezione-ultra-premium-30th-anniversario-espeon-ita-max-1-per-persona"},
        ],
    },
    {
        "product_id": "30th_celebration_upc_night",
        "product_name": "Pokémon 30° Anniversario UPC Notte (Umbreon)",
        "retailers": [
            {"name": "CarteMagic", "url": "https://www.cartemagic.com/prodotto/pokemon-30-anniversario-collezione-ultra-premium-umbreon-ita/"},
        ],
    },
    {
        "product_id": "30th_celebration_upc_bundle",
        "product_name": "Pokémon 30° Anniversario UPC Bundle Giorno+Notte",
        "retailers": [
            {"name": "Baruzcard", "url": "https://baruzcard.it/products/pokemon-30-anniversario-bundle-collezioni-ultra-premium-umbreon-ex-espeon-ex-it"},
        ],
    },
    {
        "product_id": "30th_celebration_etb",
        "product_name": "Pokémon 30° Anniversario Set Allenatore Fuoriclasse (ETB)",
        "retailers": [
            {"name": "Maximus.be", "url": "https://maximus.be/product/pokemon-30th-celebration-elite-trainer-box/"},
            {"name": "Baruzcard", "url": "https://baruzcard.it/products/pokemon-30-anniversario-set-allenatore-fuoriclasse-ita"},
            # I 3 sotto: trovati oggi con il nome italiano corretto, ma NON
            # ancora verificati con un fetch diretto — il primo controllo
            # registra solo lo stato di partenza, come sempre.
            {"name": "mattoncinostore.it", "url": "https://mattoncinostore.it/prodotto/set-allenatore-fuoriclasse-30-anniversario-it-preorder/"},
            {"name": "ilcovodelnerd.com", "url": "https://www.ilcovodelnerd.com/shop/prodotti-sigillati/pokemon/pokemon-30-anniversario-set-allenatore-fuoriclasse-etb-ita/"},
            {"name": "manuelpoke3.it", "url": "https://manuelpoke3.it/products/set-allenatore-fuoriclasse-pokemon-30-anniversario-it"},
        ],
    },
]

# eBay è diverso dagli altri: non ha una singola pagina prodotto con uno
# stato "disponibile/esaurito" — ha tante inserzioni di venditori diversi.
# Qui usiamo la stessa logica di ebay_new_listing_scanner.py (nuove
# inserzioni + le 3 col prezzo UNITARIO più basso, sempre — vedi
# unit_price/detect_quantity per i bundle da 2+ pezzi).
#
# NOTA SU QUESTO CONTROLLO: da qui in avanti gira sul job orario dedicato
# (ebay_check.yml / ebay_check_main.py, stato in ebay_state.json), NON più
# insieme al controllo scorte rivenditori ogni 20 minuti — troppi post,
# e per eBay un ritardo di un'ora non cambia granché rispetto a un ritardo
# di 20 minuti, a differenza di un preordine diretto che può esaurirsi in
# pochi minuti.
#
# STRUTTURA UPC: Giorno e Notte sono UNITI in un solo pool prezzi per
# lingua (sono nella stessa fascia di prezzo, a differenza di ETB vs UPC —
# per questo l'ETB resta un prodotto a sé) — ma il pool inglese e quello
# italiano restano SEPARATI e postati separatamente, come richiesto: "in
# ITA un monitoraggio, in altra lingua l'altro". La query "generica" senza
# Day/Night esplicito (es. "...Ultra Premium Collection") è inclusa apposta
# per catturare le inserzioni bundle che vendono Giorno+Notte insieme e
# magari non ripetono "Day"/"Night" per ciascuno nel titolo.
#
# "ebay_include_any_of"/"ebay_exclude" (opzionali): filtro anti-falsi-
# positivi, si sommano a EXCLUDE + EBAY_LISTING_EXCLUDE di keywords.py
# (che ora esclude anche le custodie magnetiche/acriliche).
EBAY_WATCHLIST = [
    {
        "product_id": "30th_celebration_etb",
        "product_name": "Pokémon 30° Anniversario Set Allenatore Fuoriclasse (ETB)",
        "queries": [
            "Pokemon 30th Celebration Elite Trainer Box",
            "Pokemon Set Allenatore Fuoriclasse 30 Anniversario",
        ],
        "ebay_include_any_of": [
            ["elite trainer box", "etb", "allenatore fuoriclasse"],
            ["30th", "30°", "30 anniversario", "celebration"],
        ],
        "ebay_exclude": ["scarlet violet", "sword shield", "sun moon", "ultra premium", "upc"],
    },
    {
        "product_id": "30th_celebration_upc_eng",
        "product_name": "Pokémon 30° Anniversario Ultra Premium Collection (EN)",
        "queries": [
            "Pokemon 30th Celebration Ultra Premium Collection Day Espeon",
            "Pokemon 30th Celebration Ultra Premium Collection Night Umbreon",
            "Pokemon 30th Celebration Ultra Premium Collection",
        ],
        "ebay_include_any_of": [
            ["ultra premium", "upc"],
            ["day", "night", "espeon", "umbreon", "giorno", "notte"],
        ],
        "ebay_exclude": [
            "scarlet violet", "sword shield", "sun moon",
            "elite trainer box", "etb", "allenatore fuoriclasse",
        ],
    },
    {
        "product_id": "30th_celebration_upc_ita",
        "product_name": "Pokémon 30° Anniversario Ultra Premium Collection (ITA)",
        "queries": [
            "Pokemon 30 Anniversario Ultra Premium Giorno Espeon",
            "Pokemon 30 Anniversario Ultra Premium Notte Umbreon",
            "Pokemon 30 Anniversario Collezione Ultra Premium",
        ],
        "ebay_include_any_of": [
            ["ultra premium", "upc", "collezione"],
            ["day", "night", "espeon", "umbreon", "giorno", "notte"],
        ],
        "ebay_exclude": [
            "scarlet violet", "sword shield", "sun moon",
            "elite trainer box", "etb", "allenatore fuoriclasse",
        ],
    },
]
