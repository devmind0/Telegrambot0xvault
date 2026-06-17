0xVault Telegram Bot

Render kurulumu

Build Command:
pip install -r requirements.txt

Start Command:
python main.py

Environment Variables:
TELEGRAM_BOT_TOKEN
GEMINI_API_KEY
ALLOWED_CHAT_ID=-3811673849
GEMINI_MODEL=gemini-2.5-flash
GEMINI_AUTH_MODE=key
CHAT_RATE_LIMIT_COUNT=8
CHAT_RATE_LIMIT_WINDOW_SECONDS=60
REPORT_RATE_LIMIT_COUNT=5
REPORT_RATE_LIMIT_WINDOW_SECONDS=300
AI_TIMEOUT_SECONDS=30
LOG_LEVEL=INFO

Health check:
/
/health

Telegram komutları:
/help
/chat <mesaj>
/report
/exitreport
/cancel
