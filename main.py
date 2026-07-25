"""
Новинний бот для акцій.
Читає список тікерів з tickers.txt, отримує свіжі новини через Finnhub
(company-news), рахує sentiment самостійно за словами-маркерами,
перекладає новини на українську і надсилає в Telegram ОДНЕ зведене
повідомлення на компанію (якщо сигнал сильний, >= THRESHOLD).
"""

import os
import json
import pathlib
import datetime
import requests

try:
    from deep_translator import GoogleTranslator
except ImportError:
    GoogleTranslator = None

FINNHUB_KEY = os.environ["FINNHUB_API_KEY"]
TG_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TG_CHAT = os.environ["TELEGRAM_CHAT_ID"]

THRESHOLD = 0.80
MIN_MENTIONS = 3
MAX_NEWS_PER_MESSAGE = 5      # скільки новин максимум показувати в одному зведеному повідомленні
SUMMARY_MAX_CHARS = 220       # обрізаємо довгі описи новин перед перекладом/показом

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


def get_company_name(ticker):
    url = "https://finnhub.io/api/v1/stock/profile2"
    try:
        r = requests.get(url, params={"symbol": ticker, "token": FINNHUB_KEY}, timeout=15)
        r.raise_for_status()
        data = r.json()
        return data.get("name") or ticker
    except Exception as e:
        print(f"[{ticker}] не вдалось отримати назву компанії: {e}")
        return ticker


def score_text(text):
    text_lower = text.lower()
    pos = sum(1 for w in POSITIVE_WORDS if w in text_lower)
    neg = sum(1 for w in NEGATIVE_WORDS if w in text_lower)
    return pos, neg


def matched_keywords(text):
    text_lower = text.lower()
    pos_found = sorted(set(w for w in POSITIVE_WORDS if w in text_lower))
    neg_found = sorted(set(w for w in NEGATIVE_WORDS if w in text_lower))
    return pos_found, neg_found


def translate_to_uk(text):
    if not text:
        return text
    if GoogleTranslator is None:
        return text
    try:
        return GoogleTranslator(source="auto", target="uk").translate(text)
    except Exception as e:
        print(f"Помилка перекладу: {e}")
        return text


def send_telegram(text):
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    resp = requests.post(
        url,
        data={
            "chat_id": TG_CHAT,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=15,
    )
    if not resp.ok:
        print(f"Помилка Telegram: {resp.status_code} {resp.text}")


def build_message(ticker, company_name, verdict_emoji, verdict_label, share_pct,
                   pos_count, neg_count, pos_words, neg_words, impact_text, news_items):
    lines = []
    lines.append(f"📊 <b>{ticker} — {company_name}</b>")
    lines.append("━━━━━━━━━━━━━━━")
    lines.append(f"{verdict_emoji} <b>{verdict_label}</b> ({share_pct:.0f}%)")

    keywords_str_parts = []
    if pos_words:
        keywords_str_parts.append("позитивні: " + ", ".join(pos_words))
    if neg_words:
        keywords_str_parts.append("негативні: " + ", ".join(neg_words))
    keywords_str = " | ".join(keywords_str_parts)
    lines.append(f"Ключові слова ({pos_count} поз. / {neg_count} нег.): {keywords_str}")
    lines.append("")
    lines.append(f"💡 {impact_text}")
    lines.append("")
    lines.append(f"📰 Новини ({len(news_items)}):")

    for i, item in enumerate(news_items, start=1):
        headline_uk = translate_to_uk(item.get("headline", ""))
        summary_raw = (item.get("summary") or "")[:SUMMARY_MAX_CHARS]
        summary_uk = translate_to_uk(summary_raw)
        source = item.get("source", "")
        url = item.get("url", "")

        # Finnhub дає час публікації новини як unix timestamp в полі "datetime"
        published_ts = item.get("datetime")
        if published_ts:
            published_str = datetime.datetime.fromtimestamp(published_ts).strftime("%H:%M, %d.%m.%Y")
        else:
            published_str = "час невідомий"

        lines.append("")
        lines.append(f"<b>{i}. {headline_uk}</b>")
        lines.append(f"🕐 Опубліковано: {published_str}")
        if summary_uk:
            lines.append(summary_uk)
        lines.append(f"🔗 {source}: {url}")

    now = datetime.datetime.now().strftime("%H:%M, %d.%m.%Y")
    lines.append("")
    lines.append(f"⏱ Сповіщення сформовано: {now}")

    return "\n".join(lines)


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

        if bullish_share >= THRESHOLD:
            verdict_emoji = "⬆️"
            verdict_label = "СИЛЬНИЙ ПОЗИТИВНИЙ СИГНАЛ"
            share_pct = bullish_share * 100
            impact_text = (
                "Новинний фон переважно позитивний — це може підштовхнути акцію "
                "до короткострокового зростання. Це не фінансова порада, а автоматичний аналіз новин."
            )
        elif bearish_share >= THRESHOLD:
            verdict_emoji = "⬇️"
            verdict_label = "СИЛЬНИЙ НЕГАТИВНИЙ СИГНАЛ"
            share_pct = bearish_share * 100
            impact_text = (
                "Новинний фон переважно негативний — це може тиснути на акцію "
                "у бік короткострокового падіння. Це не фінансова порада, а автоматичний аналіз новин."
            )
        else:
            continue

        seen_ids = set(seen.get(ticker, []))
        new_items = []
        all_pos_words = set()
        all_neg_words = set()

        for item in news_items[:20]:
            news_id = str(item.get("id"))
            if not news_id or news_id in seen_ids:
                continue
            seen_ids.add(news_id)

            text = f"{item.get('headline', '')} {item.get('summary', '')}"
            pw, nw = matched_keywords(text)
            all_pos_words.update(pw)
            all_neg_words.update(nw)

            new_items.append(item)

        if not new_items:
            # Сигнал сильний, але всі новини вже надсилались раніше — не дублюємо
            seen[ticker] = list(seen_ids)[-50:]
            continue

        new_items = new_items[:MAX_NEWS_PER_MESSAGE]

        company_name = get_company_name(ticker)

        message = build_message(
            ticker=ticker,
            company_name=company_name,
            verdict_emoji=verdict_emoji,
            verdict_label=verdict_label,
            share_pct=share_pct,
            pos_count=total_pos,
            neg_count=total_neg,
            pos_words=sorted(all_pos_words),
            neg_words=sorted(all_neg_words),
            impact_text=impact_text,
            news_items=new_items,
        )
        send_telegram(message)

        seen[ticker] = list(seen_ids)[-50:]

    save_seen(seen)


if __name__ == "__main__":
    main()
