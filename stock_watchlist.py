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
        "product_name": "Pokémon 30° Anniversario Set Allenatore Fuoriclasse",
        "retailers": [
            {"name": "Maximus.be", "url": "https://maximus.be/product/pokemon-30th-celebration-elite-trainer-box/"},
        ],
    },
]
