# Crypto Analysis Bot

A Telegram bot that analyzes crypto tokens using Fundamental Analysis, Technical Analysis, and Market Sentiment — combined into one trade signal.

Built entirely on mobile using Termux + Python.

## Features

- /signal <token> — Trade signal combining FA + TA + Sentiment
- /analyze <token> — Deep fundamental analysis with scorecard
- /price <token> — Quick price snapshot
- /compare <token1> <token2> — Side-by-side comparison
- /sentiment — Current Fear & Greed Index

## Setup

1. Get a Telegram Bot Token from @BotFather
2. Get a free Groq API Key from console.groq.com
3. Add your keys to bot.py
4. Run: pip install -r requirements.txt
5. Run: python bot.py

## APIs Used

- CoinGecko — Price and market data (free)
- Alternative.me — Fear & Greed Index (free)
- Groq — AI analysis with Llama 3.3 70B (free)

## Disclaimer

For educational purposes only. Not financial advice.

## Built By

0xmaleeq — Crypto trader building tools to amplify trading skills.