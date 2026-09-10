"""
telegram_polling_bot.py — Bot Telegram in polling, per provare SUBITO la
ricerca on-demand dal tuo computer, senza impostare infrastruttura cloud.

Come funziona: chiama ripetutamente getUpdates in long-polling (Telegram
stessa aspetta fino a `timeout` secondi se non c'è nulla di nuovo, invece di
martellare richieste a vuoto). Per ogni messaggio nuovo, chiama
on_demand_lookup.query_product() e rimanda indietro la risposta.

QUESTO È SOLO PER TEST LOCALE, non per produzione — se lo lasci girare
mentre sei al PC funziona benissimo per provarlo, ma per un uso continuo
servirebbe uno dei percorsi discussi nel README (servizio cloud o webhook).
Anche i costi valgono solo qui: ogni messaggio che scrivi fa una vera
chiamata Claude con web search a consumo, non è gratis come gli scanner
schedulati.

Uso:
  pip install anthropic requests
  export TELEGRAM_BOT_TOKEN=...   (lo stesso del bot già configurato)
  export ANTHROPIC_API_KEY=...    (dalla tua console Anthropic)
  python telegram_polling_bot.py

Poi scrivi al bot su Telegram (es. "Riftbound Teemo capodanno") e aspetta
la risposta — la prima potrebbe metterci qualche secondo, fa una ricerca
web vera.
"""

from __future__ import annotations

import os
import time

import requests

from on_demand_lookup import query_product, SYSTEM_PROMPT


class RealAnthropicClient:
    """Implementazione vera dell'interfaccia AnthropicClient di
    on_demand_lookup.py — quella che finora era testata solo con un fake."""

    def __init__(self, api_key: str, model: str = "claude-sonnet-5"):
        import anthropic
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def search_product_prices(self, query: str, days_back: int) -> str:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=2048,
            system=SYSTEM_PROMPT.format(days_back=days_back),
            messages=[{"role": "user", "content": f"Cerca vendite concluse recenti per: {query}"}],
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}],
        )
        return "".join(block.text for block in response.content if block.type == "text")


def get_updates(bot_token: str, offset: int, timeout: int = 30) -> list:
    url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
    resp = requests.get(url, params={"offset": offset, "timeout": timeout}, timeout=timeout + 10)
    resp.raise_for_status()
    return resp.json().get("result", [])


def send_message(bot_token: str, chat_id, text: str) -> None:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    requests.post(url, data={"chat_id": chat_id, "text": text, "disable_web_page_preview": True})


def run_polling_loop(bot_token: str, client: RealAnthropicClient) -> None:
    offset = 0
    print("Bot in ascolto — scrivi il nome di un prodotto/carta su Telegram. Ctrl+C per fermare.")
    while True:
        try:
            updates = get_updates(bot_token, offset, timeout=30)
        except requests.RequestException as e:
            print(f"[errore rete, riprovo tra 5s] {e}")
            time.sleep(5)
            continue

        for update in updates:
            offset = update["update_id"] + 1
            message = update.get("message")
            if not message or "text" not in message:
                continue
            chat_id = message["chat"]["id"]
            text = message["text"].strip()
            if text.startswith("/"):
                continue  # ignora comandi tipo /start per questo test minimale
            print(f"[ricevuto] chat={chat_id}: {text!r} — cerco...")
            try:
                reply = query_product(client, text, days_back=90)
            except Exception as e:
                reply = f"Errore durante la ricerca: {e}"
            send_message(bot_token, chat_id, reply)
            print(f"[risposto] chat={chat_id}")


def main() -> int:
    if "TELEGRAM_BOT_TOKEN" not in os.environ or "ANTHROPIC_API_KEY" not in os.environ:
        print("ERRORE: servono TELEGRAM_BOT_TOKEN e ANTHROPIC_API_KEY come variabili d'ambiente")
        return 1

    client = RealAnthropicClient(os.environ["ANTHROPIC_API_KEY"])
    run_polling_loop(os.environ["TELEGRAM_BOT_TOKEN"], client)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
