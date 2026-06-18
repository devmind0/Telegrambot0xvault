import importlib.util
import logging
import os
import sys
import tempfile
import urllib.request
from threading import Thread

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

RAW_MAIN_URL = os.getenv(
    "BOT_MAIN_URL",
    "https://raw.githubusercontent.com/devmind0/Telegrambot0xvault/main/main.py",
)

app = FastAPI()
_bot_module = None
_startup_error = ""


def load_remote_main():
    global _bot_module
    if _bot_module is not None:
        return _bot_module
    path = os.path.join(tempfile.gettempdir(), "oxvault_main.py")
    try:
        with urllib.request.urlopen(RAW_MAIN_URL, timeout=30) as response:
            code = response.read().decode("utf-8")
        compile(code, path, "exec")
        with open(path, "w", encoding="utf-8") as file:
            file.write(code)
        spec = importlib.util.spec_from_file_location("oxvault_main", path)
        module = importlib.util.module_from_spec(spec)
        sys.modules["oxvault_main"] = module
        spec.loader.exec_module(module)
        module.validate_config()
        _bot_module = module
        logging.info("0xVault Telegram webhook app loaded version=%s", getattr(module, "APP_VERSION", "unknown"))
        return module
    except Exception as exc:
        raise RuntimeError(f"main.py GitHub raw kaynağından yüklenemedi: {exc}") from exc


def message_text(message):
    return (message.get("text") or message.get("caption") or "").strip()


def command_and_args(text):
    if not text.startswith("/"):
        return "", ""
    first, _, rest = text.partition(" ")
    command = first.split("@", 1)[0].lower()
    return command, rest.strip()


def webhook_method(chat_id, text, reply_to=None):
    payload = {
        "method": "sendMessage",
        "chat_id": chat_id,
        "text": (text or "Tamam.").strip() or "Tamam.",
        "disable_web_page_preview": True,
    }
    if reply_to:
        payload["reply_to_message_id"] = reply_to
    return payload


def quick_process(update):
    bot = load_remote_main()
    message = update.get("message") if isinstance(update, dict) else None
    if not message:
        return {"ok": True}
    text = message_text(message)
    chat = message.get("chat", {})
    chat_id = chat.get("id", 0)
    msg_id = message.get("message_id")
    user_id = message.get("from", {}).get("id", 0)
    command, args = command_and_args(text)

    if not bot.is_allowed(message):
        return {"ok": True}

    state = bot.user_state[user_id]

    if state.get(bot.REPORT_AWAITING_LANGUAGE) and command not in {"/tr", "/en", "/cancel", "/exitreport"}:
        return webhook_method(
            chat_id,
            "Şu an rapor modundasın, diğer komutlar çalışamaz. /cancel veya /exitreport kodlarını dene.",
            msg_id,
        )

    if command == "/help":
        return webhook_method(chat_id, bot.HELP_TR, msg_id)

    if command == "/cancel":
        bot.clear_user(user_id)
        return webhook_method(chat_id, "İptal edildi. Aktif işlem durduruldu.", msg_id)

    if command == "/exitreport":
        if state.get(bot.REPORT_MODE) or state.get(bot.REPORT_AWAITING_LANGUAGE) or state.get(bot.REPORT_PENDING_TEXT):
            state.pop(bot.REPORT_MODE, None)
            state.pop(bot.REPORT_DRAFT, None)
            state.pop(bot.REPORT_AWAITING_LANGUAGE, None)
            state.pop(bot.REPORT_PENDING_TEXT, None)
            state.pop(bot.REPORT_PENDING_ANALYSIS, None)
            state.pop(bot.REPORT_PENDING_IMAGE_NOTE, None)
            return webhook_method(chat_id, "Rapor modundan çıkıldı.", msg_id)
        return webhook_method(chat_id, "Aktif rapor modu yok.", msg_id)

    if command == "/report" and not args:
        return webhook_method(chat_id, bot.REPORT_INTRO_TR, msg_id)

    if command == "/report" and args and not message.get("photo"):
        allowed, retry = bot.allow_rate(user_id, "report", bot.REPORT_RATE_LIMIT_COUNT, bot.REPORT_RATE_LIMIT_WINDOW_SECONDS)
        if not allowed:
            return webhook_method(chat_id, f"Rapor üretim limiti aşıldı. {retry} saniye sonra tekrar dene.", msg_id)
        analysis = bot.analyze_report(args.strip())
        if not analysis["complete"]:
            return webhook_method(chat_id, bot.missing_message(analysis["missing"]), msg_id)
        state[bot.REPORT_PENDING_TEXT] = args.strip()
        state[bot.REPORT_PENDING_ANALYSIS] = analysis
        state[bot.REPORT_PENDING_IMAGE_NOTE] = ""
        state[bot.REPORT_AWAITING_LANGUAGE] = True
        return webhook_method(chat_id, bot.report_language_question(), msg_id)

    if command in {"/tr", "/en"}:
        if not state.get(bot.REPORT_AWAITING_LANGUAGE):
            return webhook_method(chat_id, "Bekleyen rapor yok. Önce /report <sorunu anlat> yaz.", msg_id)
        Thread(target=bot.handle_report_language, args=(message, "en" if command == "/en" else "tr"), daemon=True).start()
        return webhook_method(chat_id, "Rapor hazırlanıyor, birazdan gönderilecek.", msg_id)

    if command == "/chat" or message.get("photo") or command == "/report":
        Thread(target=bot.handle_message, args=(message,), daemon=True).start()
        return webhook_method(chat_id, "İsteğini aldım, işliyorum. Sonuç birazdan gönderilecek.", msg_id)

    return {"ok": True}


@app.on_event("startup")
def startup_event():
    global _startup_error
    try:
        load_remote_main()
    except Exception as exc:
        _startup_error = str(exc)
        logging.exception("0xVault webhook app startup failed")


@app.get("/")
def root():
    version = "unknown"
    if _bot_module is not None:
        version = getattr(_bot_module, "APP_VERSION", "unknown")
    return {
        "status": "ok" if not _startup_error else "error",
        "mode": "telegram_webhook_fast_ack",
        "service": "0xVault Telegram Bot",
        "version": version,
        "error": _startup_error,
    }


@app.get("/health")
def health():
    return {"status": "ok", "error": _startup_error}


@app.post("/telegram")
async def telegram_webhook(request: Request):
    try:
        update = await request.json()
        return JSONResponse(quick_process(update))
    except Exception as exc:
        logging.exception("telegram webhook failed")
        return JSONResponse({"ok": True, "error": str(exc)})
