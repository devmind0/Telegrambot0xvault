import importlib.util
import json
import logging
import os
import sys
import tempfile
import urllib.request

from fastapi import FastAPI, Request
from fastapi.responses import Response

RAW_MAIN_URL = os.getenv(
    "BOT_MAIN_URL",
    "https://raw.githubusercontent.com/devmind0/Telegrambot0xvault/main/main.py",
)

app = FastAPI()
_bot_module = None
_startup_error = ""


TR_ASCII_MAP = str.maketrans({
    "ç": "c", "Ç": "C",
    "ğ": "g", "Ğ": "G",
    "ı": "i", "İ": "I",
    "ö": "o", "Ö": "O",
    "ş": "s", "Ş": "S",
    "ü": "u", "Ü": "U",
})


def stable_text(text):
    text = str(text or "OK")
    return text.translate(TR_ASCII_MAP).replace("﻿", "").replace("​", "")

ASCII_HELP = """
0xVault Cyber Security Bot komutlari:

/chat <mesaj>
Siber guvenlik, bug bounty, guvenli kod ve savunma sorularina cevap verir.

/report <sorunu anlat>
Bug bounty raporu icin bilgileri kontrol eder, sonra /tr veya /en dil secimi ister.

/tr
Bekleyen raporu Turkce hazirlar.

/en
Bekleyen raporu English hazirlar.

/exitreport
Rapor akisini kapatir.

/cancel
Aktif islemi iptal eder.

Komutsuz mesajlar ve komutsuz fotograflar yok sayilir. Fotograf icin /chat veya /report kullanilsa bile bot fotograf goremez; icerigi metin olarak yazman gerekir.
""".strip()


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
        with urllib.request.urlopen(RAW_MAIN_URL, timeout=20) as response:
            code = response.read().decode("utf-8")
        compile(code, path, "exec")
        with open(path, "w", encoding="utf-8") as file:
            file.write(code)
        spec = importlib.util.spec_from_file_location("oxvault_main", path)
        module = importlib.util.module_from_spec(spec)
        sys.modules["oxvault_main"] = module
        spec.loader.exec_module(module)
        module.validate_config()
        module.AI_TIMEOUT_SECONDS = min(int(getattr(module, "AI_TIMEOUT_SECONDS", 30)), 8)
        _bot_module = module
        logging.info("0xVault Telegram webhook app loaded version=%s", getattr(module, "APP_VERSION", "unknown"))
        return module
    except Exception as exc:
        raise RuntimeError(f"main.py GitHub raw kaynagindan yuklenemedi: {exc}") from exc


def message_text(message):
    return (message.get("text") or message.get("caption") or "").strip()


def command_and_args(text):
    if not text.startswith("/"):
        return "", ""
    first, _, rest = text.partition(" ")
    command = first.split("@", 1)[0].lower()
    return command, rest.strip()


def webhook_method(chat_id, text, reply_to=None):
    text = stable_text(text).strip() or "OK"
    if len(text) > 3900:
        text = text[:3890].rstrip() + "..."
    payload = {
        "method": "sendMessage",
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    if reply_to:
        payload["reply_to_message_id"] = reply_to
    return payload


def capture_response(bot, call):
    responses = []
    original_send_message = bot.send_message

    def capture_send_message(chat_id, text, reply_to=None):
        responses.append(webhook_method(chat_id, text, reply_to))

    bot.send_message = capture_send_message
    try:
        call()
    except Exception:
        logging.exception("bot command failed")
        responses.append(webhook_method(0, "Islem sirasinda hata olustu. Lutfen tekrar dene."))
    finally:
        bot.send_message = original_send_message
    if responses:
        return responses[0]
    return {"ok": True}


def cancel_report_state(bot, state):
    state.pop(bot.REPORT_MODE, None)
    state.pop(bot.REPORT_DRAFT, None)
    state.pop(bot.REPORT_AWAITING_LANGUAGE, None)
    state.pop(bot.REPORT_PENDING_TEXT, None)
    state.pop(bot.REPORT_PENDING_ANALYSIS, None)


def welcome_name(member):
    username = (member.get("username") or "").strip()
    if username:
        return "@" + username
    full_name = " ".join(part for part in [member.get("first_name", ""), member.get("last_name", "")] if part).strip()
    return full_name or "dostum"


def welcome_message(member):
    name = welcome_name(member)
    return (
        f"Selam, hos geldin {name}.\n\n"
        "0xVault grubuna katildin. Burası siber guvenlik, bug bounty, guvenli kod ve savunma odakli calisma alanidir. "
        "Paylasimlarda kapsam, izin ve profesyonel etik kurallara dikkat edelim."
    )


def quick_process(update):
    bot = load_remote_main()
    message = update.get("message") if isinstance(update, dict) else None
    if not message:
        return {"ok": True}

    chat = message.get("chat", {})
    chat_id = chat.get("id", 0)
    msg_id = message.get("message_id")

    if not bot.is_allowed(message):
        return {"ok": True}

    new_members = message.get("new_chat_members") or []
    if new_members:
        bot_id = None
        try:
            bot_id = int(str(bot.TELEGRAM_BOT_TOKEN).split(":", 1)[0])
        except Exception:
            bot_id = None
        real_members = [member for member in new_members if not member.get("is_bot") or member.get("id") != bot_id]
        if real_members:
            return webhook_method(chat_id, welcome_message(real_members[0]), msg_id)
        return {"ok": True}

    text = message_text(message)
    has_photo = bool(message.get("photo"))
    user_id = message.get("from", {}).get("id", 0)
    command, args = command_and_args(text)

    if has_photo:
        if command in {"/chat", "/report"}:
            return webhook_method(chat_id, "Fotograf bakamiyorum. Lutfen gorseldeki hata veya icerigi metin olarak yaz.", msg_id)
        return {"ok": True}

    state = bot.user_state[user_id]

    if state.get(bot.REPORT_AWAITING_LANGUAGE) and command not in {"/tr", "/en", "/cancel", "/exitreport"}:
        return webhook_method(chat_id, "Su an rapor modundasin. /tr, /en, /cancel veya /exitreport kullan.", msg_id)

    if command == "/help":
        return webhook_method(chat_id, ASCII_HELP, msg_id)

    if command == "/cancel":
        bot.clear_user(user_id)
        return webhook_method(chat_id, "Iptal edildi. Aktif islem durduruldu.", msg_id)

    if command == "/exitreport":
        if state.get(bot.REPORT_AWAITING_LANGUAGE) or state.get(bot.REPORT_PENDING_TEXT) or state.get(bot.REPORT_MODE):
            cancel_report_state(bot, state)
            return webhook_method(chat_id, "Rapor modundan cikildi.", msg_id)
        return webhook_method(chat_id, "Aktif rapor modu yok.", msg_id)

    if command == "/report":
        if not args:
            return webhook_method(chat_id, bot.REPORT_INTRO_TR, msg_id)
        return capture_response(bot, lambda: bot.handle_report_text(message, args))

    if command in {"/tr", "/en"}:
        if not state.get(bot.REPORT_AWAITING_LANGUAGE):
            return webhook_method(chat_id, "Bekleyen rapor yok. Once /report <sorunu anlat> yaz.", msg_id)
        return capture_response(bot, lambda: bot.handle_report_language(message, "en" if command == "/en" else "tr"))

    if command == "/chat":
        return capture_response(bot, lambda: bot.handle_chat(message, args))

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
        "mode": "telegram_webhook_photo_gated_localized_report",
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
