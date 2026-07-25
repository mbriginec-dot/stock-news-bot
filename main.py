"""
Новинний бот для акцій.
Читає список тікерів з tickers.txt, перевіряє sentiment новин через Finnhub,
і надсилає в Telegram сповіщення про новини компаній із сильним (>=80%)
позитивним або негативним новинним фоном.
"""

import os
import json
import pathlib
import datetime
import requests

FINNHUB_KEY = os.environ["FINNHUB_API_KEY"]
TG_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TG_CHAT = os.environ["TELEGRAM_CHAT_ID"]

THRESHOLD = 0.80

TICKERS_FILE = "tickers.txt"
SEEN_FILE = "seen_news.json"


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


def get_sentiment(ticker):
    url = "https://finnhub.io/api/v1/news-sentiment"
    r = requests.get(url, params={"symbol": ticker, "token": FINNHUB_KEY}, timeout=15)
    r.raise_for_status()
    return r.json()


def get_company_news(ticker):
    today = datetime.date.today()
    frm = today - datetime.timedelta(days=1)
    url = "https://finnhub.io/api/v1/company-news"
    r = requests.get(
        url,
        params={"symbol": ticker, "from": str(frm), "to": str(today), "token": FINNHUB_KEY},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


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
            sentiment = get_sentiment(ticker)
        except Exception as e:
            print(f"[{ticker}] помилка sentiment: {e}")
            continue

        s = sentiment.get("sentiment", {})
        bullish = s.get("bullishPercent", 0)
        bearish = s.get("bearishPercent", 0)

        verdict = None
        if bullish >= THRESHOLD:
            verdict = f"⬆️ Сильний позитивний новинний фон ({bullish * 100:.0f}% бичачих новин за тиждень)"
        elif bearish >= THRESHOLD:
            verdict = f"⬇️ Сильний негативний новинний фон ({bearish * 100:.0f}% ведмежих новин за тиждень)"

        if verdict is None:
            continue

        try:
            news_items = get_company_news(ticker)
        except Exception as e:
            print(f"[{ticker}] помилка новин: {e}")
            continue

        seen_ids = set(seen.get(ticker, []))

        for item in news_items[:10]:
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
