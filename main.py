"""
Новинний бот для акцій.
Читає список тікерів з tickers.txt, отримує свіжі новини через Finnhub
(безкоштовний ендпоінт company-news) і рахує sentiment самостійно
за допомогою простого аналізу ключових слів у заголовках/описах.
Надсилає в Telegram нові новини по компаніях із сильним (>=80%)
позитивним або негативним фоном.
"""

import os
import json
import pathlib
import datetime
import requests

FINNHUB_KEY = os.environ["FINNHUB_API_KEY"]
TG_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TG_CHAT = os.environ["TELEGRAM_CHAT_ID"]

THRESHOLD = 0.80          # частка позитивних/негативних згадок, щоб вважати сигнал сильним
MIN_MENTIONS = 3          # мінімум ключових слів за період, щоб не реагувати на "тишу"

TICKERS_FILE = "tickers.txt"
SEEN_FILE = "seen_news.json"

POSITIVE_WORDS = [
    "surge", "soar", "jump", "beat", "beats", "upgrade", "upgraded", "record",
    "growth", "profit", "strong", "rally", "outperform", "bullish", "gain",
    "gains", "rise", "rises", "positive", "expand", "expansion", "breakthrough",
    "wins", "win", "boost", "boosts", "raises", "raised", "exceeds", "top",
]

NEGATIVE_WORDS = [
    "plunge", "plunges", "drop", "drops", "fall", "falls", "miss", "misses",
    "downgrade", "downgraded", "loss", "losses", "weak", "decline", "declines",
    "lawsuit", "investigation", "bearish", "cut", "cuts", "recall", "fraud",
    "negative", "slump", "warns", "warning", "layoffs", "layoff", "probe",
    "delay", "delays", "halts", "halt",
]


def load_tickers():
    with open(TICKERS_FILE, encoding="utf-8") as f:
        return [line.strip().upper() for line in f if line.strip()]


def load_seen():
    path = pathlib.Path(SEEN_FILE)
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_seen(seen):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False, indent=2)


def get_company_news(ticker, days_back=1):
    today = datetime.date.today()
    frm = today - datetime.timedelta(days=days_back)
    url = "https://finnhub.io/api/v1/company-news"
    r = requests.get(
        url,
        params={"symbol": ticker, "from": str(frm), "to": str(today), "token": FINNHUB_KEY},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


def score_text(text):
    """Рахує кількість позитивних і негативних слів-маркерів у тексті."""
    text_lower = text.lower()
    pos = sum(1 for w in POSITIVE_WORDS if w in text_lower)
    neg = sum(1 for w in NEGATIVE_WORDS if w in text_lower)
    return pos, neg


def send_telegram(text):
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    resp = requests.post(
        url,
        data={
            "chat_id": TG_CHAT,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        },
        timeout=15,
    )
    if not resp.ok:
        print(f"Помилка Telegram: {resp.status_code} {resp.text}")


def main():
    tickers = load_tickers()
    seen = load_seen()

    for ticker in tickers:
        try:
            news_items = get_company_news(ticker)
        except Exception as e:
            print(f"[{ticker}] помилка новин: {e}")
            continue

        total_pos = 0
        total_neg = 0
        for item in news_items[:20]:
            text = f"{item.get('headline', '')} {item.get('summary', '')}"
            p, n = score_text(text)
            total_pos += p
            total_neg += n

        total_mentions = total_pos + total_neg
        print(f"{ticker}: pos={total_pos}, neg={total_neg}, total_news={len(news_items)}")

        if total_mentions < MIN_MENTIONS:
            continue

        bullish_share = total_pos / total_mentions
        bearish_share = total_neg / total_mentions

        verdict = None
        if bullish_share >= THRESHOLD:
            verdict = f"⬆️ Сильний позитивний новинний фон ({bullish_share * 100:.0f}% позитивних згадок)"
        elif bearish_share >= THRESHOLD:
            verdict = f"⬇️ Сильний негативний новинний фон ({bearish_share * 100:.0f}% негативних згадок)"

        if verdict is None:
            continue

        seen_ids = set(seen.get(ticker, []))

        for item in news_items[:20]:
            news_id = str(item.get("id"))
            if not news_id or news_id in seen_ids:
                continue

            seen_ids.add(news_id)

            headline = item.get("headline", "(без заголовка)")
            url = item.get("url", "")
            source = item.get("source", "")

            message = (
                f"<b>{ticker}</b> — {source}\n"
                f"{headline}\n"
                f"{url}\n\n"
                f"{verdict}"
            )
            send_telegram(message)

        seen[ticker] = list(seen_ids)[-50:]

    save_seen(seen)


if __name__ == "__main__":
    main()
