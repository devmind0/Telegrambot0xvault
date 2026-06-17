---
title: 0xVault Telegram Bot
emoji: 🛡️
colorFrom: gray
colorTo: blue
sdk: docker
pinned: false
---

0xVault Telegram Bot

Hugging Face Spaces Docker deployment.

Required Space Secrets:
TELEGRAM_BOT_TOKEN
GEMINI_API_KEY

Required Space Variables:
ALLOWED_CHAT_ID=-3811673849
GEMINI_MODEL=gemini-2.5-flash
GEMINI_AUTH_MODE=key
CHAT_RATE_LIMIT_COUNT=8
CHAT_RATE_LIMIT_WINDOW_SECONDS=60
REPORT_RATE_LIMIT_COUNT=5
REPORT_RATE_LIMIT_WINDOW_SECONDS=300
AI_TIMEOUT_SECONDS=30
LOG_LEVEL=INFO
PORT=7860

Health endpoints:
/
/health

Telegram commands:
/help
/chat <message>
/report
/exitreport
/cancel
