import logging
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from groq import Groq

# ── Config ───────────────────────────────────────────────────────────────────
import os
from dotenv import load_dotenv

load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

groq_client = Groq(api_key=GROQ_API_KEY)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
HEADERS = {"accept": "application/json"}

# ── Data Fetching ─────────────────────────────────────────────────────────────
def search_coin_id(query):
    try:
        res = requests.get(f"https://api.coingecko.com/api/v3/search?query={query}", headers=HEADERS, timeout=10)
        coins = res.json().get("coins", [])
        return coins[0]["id"] if coins else None
    except Exception as e:
        logger.error(f"Search error: {e}")
        return None

def get_token_data(query):
    try:
        coin_id = search_coin_id(query)
        if not coin_id:
            return None
        url = f"https://api.coingecko.com/api/v3/coins/{coin_id}?localization=false&tickers=false&community_data=false&developer_data=false"
        d = requests.get(url, headers=HEADERS, timeout=10).json()
        market = d.get("market_data", {})
        return {
            "id":          coin_id,
            "name":        d.get("name", "N/A"),
            "symbol":      d.get("symbol", "N/A").upper(),
            "price":       market.get("current_price", {}).get("usd", 0) or 0,
            "market_cap":  market.get("market_cap", {}).get("usd", 0) or 0,
            "volume_24h":  market.get("total_volume", {}).get("usd", 0) or 0,
            "change_24h":  market.get("price_change_percentage_24h", 0) or 0,
            "change_7d":   market.get("price_change_percentage_7d", 0) or 0,
            "change_30d":  market.get("price_change_percentage_30d", 0) or 0,
            "supply":      market.get("circulating_supply", 0) or 0,
            "max_supply":  market.get("max_supply", None),
            "rank":        d.get("market_cap_rank", "N/A"),
            "description": d.get("description", {}).get("en", "")[:300],
            "categories":  ", ".join(d.get("categories", [])[:3]),
            "ath_change":  market.get("ath_change_percentage", {}).get("usd", 0) or 0,
        }
    except Exception as e:
        logger.error(f"CoinGecko error: {e}")
        return None

def get_price_history(coin_id, days=30):
    try:
        url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart?vs_currency=usd&days={days}&interval=daily"
        data = requests.get(url, headers=HEADERS, timeout=10).json()
        return [p[1] for p in data.get("prices", [])]
    except Exception as e:
        logger.error(f"Price history error: {e}")
        return []

def get_fear_greed():
    try:
        data = requests.get("https://api.alternative.me/fng/?limit=1", timeout=10).json()
        entry = data["data"][0]
        return {"value": int(entry["value"]), "label": entry["value_classification"]}
    except Exception:
        return {"value": 50, "label": "Neutral"}

# ── TA Calculations ───────────────────────────────────────────────────────────
def calc_rsi(prices, period=14):
    if len(prices) < period + 1:
        return None
    gains, losses = [], []
    for i in range(len(prices) - period, len(prices)):
        diff = prices[i] - prices[i - 1]
        if diff > 0:
            gains.append(diff)
        else:
            losses.append(abs(diff))
    avg_gain = sum(gains) / period if gains else 0
    avg_loss = sum(losses) / period if losses else 0
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)

def calc_ma(prices, period):
    if len(prices) < period:
        return None
    return round(sum(prices[-period:]) / period, 6)

def calc_ta(prices):
    rsi    = calc_rsi(prices)
    ma7    = calc_ma(prices, 7)
    ma25   = calc_ma(prices, 25)
    current = prices[-1] if prices else None

    if rsi is None:
        rsi_signal = "Unknown"
    elif rsi < 30:
        rsi_signal = "Oversold - Bullish signal"
    elif rsi > 70:
        rsi_signal = "Overbought - Bearish signal"
    else:
        rsi_signal = "Neutral zone"

    if ma7 and ma25 and current:
        if ma7 > ma25 and current > ma7:
            ma_signal = "Bullish - price above MAs, MA7 above MA25"
        elif ma7 < ma25 and current < ma7:
            ma_signal = "Bearish - price below MAs, MA7 below MA25"
        else:
            ma_signal = "Mixed signals"
    else:
        ma_signal = "Insufficient data"

    return {
        "rsi": rsi,
        "rsi_signal": rsi_signal,
        "ma7": ma7,
        "ma25": ma25,
        "ma_signal": ma_signal,
        "current": current,
    }

# ── AI Functions ──────────────────────────────────────────────────────────────
def ai_signal(token_data, ta, fg):
    max_supply = f"{token_data['max_supply']:,.0f}" if token_data['max_supply'] else "Unlimited"
    circ_pct   = f"{(token_data['supply']/token_data['max_supply']*100):.1f}%" if token_data['max_supply'] else "Unknown"
    rsi_str    = str(ta['rsi']) if ta['rsi'] else "N/A"
    ma7_str    = f"${ta['ma7']:,.6f}" if ta['ma7'] else "N/A"
    ma25_str   = f"${ta['ma25']:,.6f}" if ta['ma25'] else "N/A"

    prompt = f"""
You are an expert crypto trading analyst combining FA, TA, and Sentiment analysis.

TOKEN: {token_data['name']} (${token_data['symbol']})

FUNDAMENTALS:
- Price: ${token_data['price']:,.6f} | Rank: #{token_data['rank']}
- Market Cap: ${token_data['market_cap']:,.0f} | Volume 24h: ${token_data['volume_24h']:,.0f}
- 24h: {token_data['change_24h']:+.2f}% | 7d: {token_data['change_7d']:+.2f}% | 30d: {token_data['change_30d']:+.2f}%
- Supply in circulation: {circ_pct} of {max_supply}
- ATH distance: {token_data['ath_change']:+.1f}%
- Categories: {token_data['categories']}
- Description: {token_data['description']}

TECHNICAL ANALYSIS (30 days daily):
- RSI(14): {rsi_str} - {ta['rsi_signal']}
- MA7: {ma7_str} | MA25: {ma25_str}
- MA Signal: {ta['ma_signal']}

MARKET SENTIMENT:
- Fear and Greed Index: {fg['value']}/100 - {fg['label']}

Provide this exact report:

1 FUNDAMENTALS SUMMARY - Key FA points in 2-3 lines
2 TECHNICAL SIGNALS - What RSI and MAs indicate
3 SENTIMENT READING - What the Fear and Greed index means now
4 RISK ASSESSMENT - Top 2-3 risks
5 TRADE SIGNAL - Give one of: STRONG BUY / BUY / WATCH / AVOID / STRONG AVOID with clear reason
6 SUGGESTED STRATEGY - Entry zone, stop loss idea, and realistic target
7 CONFIDENCE LEVEL - Rate your confidence in this signal 1-10 with reason

Use emojis. Be direct. End with: Not financial advice - always do your own research.
"""
    response = groq_client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1400,
        temperature=0.7,
    )
    return response.choices[0].message.content

def ai_analyze(token_data):
    max_supply = f"{token_data['max_supply']:,.0f}" if token_data['max_supply'] else "Unlimited/Unknown"
    circ_pct   = f"{(token_data['supply']/token_data['max_supply']*100):.1f}%" if token_data['max_supply'] else "Unknown"
    prompt = f"""
You are a crypto fundamental analyst.

TOKEN: {token_data['name']} (${token_data['symbol']})
- Description: {token_data['description']}
- Categories: {token_data['categories']}
- Price: ${token_data['price']:,.6f} | Rank: #{token_data['rank']}
- Market Cap: ${token_data['market_cap']:,.0f} | Volume 24h: ${token_data['volume_24h']:,.0f}
- 24h: {token_data['change_24h']:+.2f}% | 7d: {token_data['change_7d']:+.2f}% | 30d: {token_data['change_30d']:+.2f}%
- Supply: {token_data['supply']:,.0f} circulating / {max_supply} max ({circ_pct} in circulation)

Provide analysis with these sections:
1 PROJECT OVERVIEW - Use case and legitimacy
2 TOKENOMICS - Supply, inflation risk
3 MARKET POSITION - Rank and competition
4 VOLUME ANALYSIS - Volume/mcap ratio signal
5 PRICE MOMENTUM - Short and mid term trend
6 RED FLAGS - Key concerns
7 GREEN FLAGS - Positives
8 SCORE - Rate each 1-5 and give overall score out of 5

Use emojis. Be concise.
"""
    response = groq_client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1200,
        temperature=0.7,
    )
    return response.choices[0].message.content

# ── Bot Commands ──────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Welcome to FA Bot v3!\n\n"
        "I combine FA + TA + Sentiment for smarter trading signals.\n\n"
        "Commands:\n"
        "/signal <token> - FA + TA + Sentiment trade signal\n"
        "/analyze <token> - Full FA report\n"
        "/price <token> - Quick price snapshot\n"
        "/compare <token1> <token2> - Side-by-side FA\n"
        "/sentiment - Current market Fear and Greed\n\n"
        "Example: /signal bitcoin"
    )

async def signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /signal <token>\nExample: /signal solana")
        return
    query = " ".join(context.args).lower().strip("$")
    msg   = await update.message.reply_text(f"Fetching data for {query.upper()}... please wait")
    data  = get_token_data(query)
    if not data:
        await msg.edit_text(f"Could not find {query.upper()}.")
        return
    await msg.edit_text(f"Calculating TA and Sentiment for {data['name']}... please wait")
    prices = get_price_history(data["id"], days=30)
    ta     = calc_ta(prices)
    fg     = get_fear_greed()
    await msg.edit_text(f"Running AI signal for {data['name']}... please wait")
    try:
        analysis = ai_signal(data, ta, fg)
        rsi_str  = str(ta['rsi']) if ta['rsi'] else "N/A"
        header   = (
            f"TRADE SIGNAL: {data['name']} (${data['symbol']})\n"
            f"Price: ${data['price']:,.6f} | RSI: {rsi_str} | F&G: {fg['value']} {fg['label']}\n"
            f"{'='*30}\n\n"
        )
        full = header + analysis
        if len(full) > 4096:
            full = full[:4090] + "..."
        await msg.edit_text(full)
    except Exception as e:
        await msg.edit_text(f"Signal failed: {str(e)}")

async def analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /analyze <token>")
        return
    query = " ".join(context.args).lower().strip("$")
    msg   = await update.message.reply_text(f"Fetching {query.upper()}... please wait")
    data  = get_token_data(query)
    if not data:
        await msg.edit_text(f"Could not find {query.upper()}.")
        return
    await msg.edit_text(f"Analyzing {data['name']}... please wait")
    try:
        analysis = ai_analyze(data)
        header   = (
            f"FA Report: {data['name']} (${data['symbol']})\n"
            f"Price: ${data['price']:,.6f} | 24h: {data['change_24h']:+.2f}% | 7d: {data['change_7d']:+.2f}%\n"
            f"{'='*30}\n\n"
        )
        full = header + analysis
        if len(full) > 4096:
            full = full[:4090] + "..."
        await msg.edit_text(full)
    except Exception as e:
        await msg.edit_text(f"Analysis failed: {str(e)}")

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /price <token>")
        return
    query = " ".join(context.args).lower().strip("$")
    data  = get_token_data(query)
    if not data:
        await update.message.reply_text(f"Token {query.upper()} not found.")
        return
    circ_pct = f"{(data['supply']/data['max_supply']*100):.1f}%" if data['max_supply'] else "N/A"
    max_s    = f"{data['max_supply']:,.0f}" if data['max_supply'] else "N/A"
    await update.message.reply_text(
        f"{data['name']} (${data['symbol']})\n\n"
        f"Price: ${data['price']:,.6f}\n"
        f"24h: {data['change_24h']:+.2f}% | 7d: {data['change_7d']:+.2f}% | 30d: {data['change_30d']:+.2f}%\n"
        f"Market Cap: ${data['market_cap']:,.0f}\n"
        f"24h Volume: ${data['volume_24h']:,.0f}\n"
        f"Rank: #{data['rank']}\n"
        f"Circulating: {data['supply']:,.0f}\n"
        f"Max Supply: {max_s}\n"
        f"% in Circulation: {circ_pct}\n"
        f"ATH Distance: {data['ath_change']:+.1f}%"
    )

async def sentiment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    fg = get_fear_greed()
    v  = fg["value"]
    if v <= 20:
        emoji, advice = "😱", "Extreme Fear - historically a buying opportunity but very high risk"
    elif v <= 40:
        emoji, advice = "😟", "Fear - market is cautious, more dips possible"
    elif v <= 60:
        emoji, advice = "😐", "Neutral - no strong bias either way"
    elif v <= 80:
        emoji, advice = "😊", "Greed - bullish market but watch for pullbacks"
    else:
        emoji, advice = "🤑", "Extreme Greed - market may be overheated, be careful"

    await update.message.reply_text(
        f"Market Sentiment {emoji}\n\n"
        f"Fear and Greed Index: {v}/100\n"
        f"Status: {fg['label']}\n\n"
        f"Meaning: {advice}\n\n"
        f"Use /signal <token> to combine this with FA and TA."
    )

async def compare(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /compare <token1> <token2>")
        return
    t1  = context.args[0].lower().strip("$")
    t2  = context.args[1].lower().strip("$")
    msg = await update.message.reply_text(f"Comparing {t1.upper()} vs {t2.upper()}... please wait")
    d1, d2 = get_token_data(t1), get_token_data(t2)
    if not d1 or not d2:
        await msg.edit_text(f"Could not find: {t1.upper() if not d1 else t2.upper()}")
        return
    prompt = f"""
Compare these two crypto tokens fundamentally. Use emojis. Give a clear final verdict.

TOKEN A: {d1['name']} (${d1['symbol']})
- Price: ${d1['price']:,.6f} | MCap: ${d1['market_cap']:,.0f} | Rank: #{d1['rank']}
- 24h: {d1['change_24h']:+.2f}% | 7d: {d1['change_7d']:+.2f}% | Volume: ${d1['volume_24h']:,.0f}
- Info: {d1['description'][:200]}

TOKEN B: {d2['name']} (${d2['symbol']})
- Price: ${d2['price']:,.6f} | MCap: ${d2['market_cap']:,.0f} | Rank: #{d2['rank']}
- 24h: {d2['change_24h']:+.2f}% | 7d: {d2['change_7d']:+.2f}% | Volume: ${d2['volume_24h']:,.0f}
- Info: {d2['description'][:200]}

Compare: Use case, Tokenomics, Market position, Momentum. Final verdict: which is fundamentally stronger?
"""
    try:
        response = groq_client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1000,
            temperature=0.7,
        )
        full = f"{d1['name']} vs {d2['name']}\n{'='*28}\n\n" + response.choices[0].message.content
        if len(full) > 4096:
            full = full[:4090] + "..."
        await msg.edit_text(full)
    except Exception as e:
        await msg.edit_text(f"Comparison failed: {str(e)}")

# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start",     start))
    app.add_handler(CommandHandler("signal",    signal))
    app.add_handler(CommandHandler("analyze",   analyze))
    app.add_handler(CommandHandler("price",     price))
    app.add_handler(CommandHandler("compare",   compare))
    app.add_handler(CommandHandler("sentiment", sentiment))
    logger.info("Bot v3 running...")
    app.run_polling()