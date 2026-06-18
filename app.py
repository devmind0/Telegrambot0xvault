import importlib.util
import json
import logging
import os
import sys
import tempfile
import urllib.request
from threading import Thread

from fastapi import FastAPI, Request
from fastapi.responses import Response

RAW_MAIN_URL = os.getenv(
    "BOT_MAIN_URL",
    "https://raw.githubusercontent.com/devmind0/Telegrambot0xvault/main/main.py",
)

app = FastAPI()
_bot_module = None
_startup_error = ""


def ascii_json(data):
    return Response(
        content=json.dumps(data, ensure_ascii=True, separators=(",", ":")),
        media_type="application/json; charset=utf-8",
    )


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


def looks_turkish(text):
    lowered = (text or "").lower()
    return any(ch in lowered for ch in "çğıöşü") or any(
        word in lowered.split() for word in ["merhaba", "selam", "nedir", "nasıl", "nasil", "çöz", "coz", "hata"]
    )


def processing_message(text):
    if looks_turkish(text):
        return "İsteğini aldım, işliyorum. Sonuç birazdan gönderilecek."
    return "I received your request and I am processing it. The result will be sent shortly."


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


def capture_first_response(bot, call):
    responses = []
    original_send_message = bot.send_message

    def capture_send_message(chat_id, text, reply_to=None):
        text = (text or "Tamam.").strip() or "Tamam."
        if len(text) > 3900:
            text = text[:3890].rstrip() + "..."
        responses.append(webhook_method(chat_id, text, reply_to))

    bot.send_message = capture_send_message
    try:
        call()
    finally:
        bot.send_message = original_send_message
    if responses:
        return responses[0]
    return {"ok": True}


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
        return capture_first_response(bot, lambda: bot.handle_message(message))

    if command == "/report" and not args:
        return webhook_method(chat_id, bot.REPORT_INTRO_TR, msg_id)

    if command == "/report" and args and not message.get("photo"):
        return capture_first_response(bot, lambda: bot.handle_report_text(message, args))

    if command in {"/tr", "/en"}:
        if not state.get(bot.REPORT_AWAITING_LANGUAGE):
            return webhook_method(chat_id, "Bekleyen rapor yok. Önce /report <sorunu anlat> yaz.", msg_id)
        return capture_first_response(bot, lambda: bot.handle_report_language(message, "en" if command == "/en" else "tr"))

    if command == "/chat" and not message.get("photo"):
        return capture_first_response(bot, lambda: bot.handle_chat(message, args))

    if command in {"/chat", "/report"}:
        Thread(target=bot.handle_message, args=(message,), daemon=True).start()
        return webhook_method(chat_id, processing_message(text), msg_id)

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
        "mode": "telegram_webhook_command_gated_ascii", 
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
        return ascii_json(quick_process(update))
    except Exception as exc:
        logging.exception("telegram webhook failed")
        return ascii_json({"ok": True, "error": str(exc)})
