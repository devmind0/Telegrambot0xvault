import importlib.util
import json
import logging
import os
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from threading import Thread

from fastapi import FastAPI, Request
from fastapi.responses import Response

RAW_MAIN_URL = os.getenv(
    "BOT_MAIN_URL",
    "https://raw.githubusercontent.com/devmind0/Telegrambot0xvault/main/main.py",
)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

app = FastAPI()
_bot_module = None
_startup_error = ""

ASCII_HELP = """
0xVault Cyber Security Bot komutlari:

/chat <mesaj>
Siber guvenlik, bug bounty, guvenli kod ve savunma sorularina cevap verir.
Fotograf yorumlatmak icin fotograf aciklamasina /chat <soru> yaz.

/report <sorunu anlat>
Bug bounty raporu icin bilgileri kontrol eder, sonra /tr veya /en dil secimi ister.
Fotografi rapora eklemek icin fotograf aciklamasina /report <bulgu> yaz.

/tr
Bekleyen raporu Turkce hazirlar.

/en
Bekleyen raporu English hazirlar.

/exitreport
Rapor akisini kapatir.

/cancel
Aktif islemi iptal eder.

Komutsuz mesaj ve komutsuz fotograf yok sayilir.
""".strip()

ASCII_REPORT_USAGE = """
Kullanim: /report <sorunu anlat>

Ornek:
/report Acik turu: IDOR. Etkilenen URL: https://example.com/api/users/123/invoices. Nasil tetikleniyor: user_id 123 yerine 124 yapilip GET request gonderiliyor. Etki/Risk: Yetkisiz kullanici baska musterinin fatura verilerini gorebiliyor. Severity: High

Zorunlu bilgiler:
Acik turu
Etkilenen URL veya endpoint
Nasil tetikleniyor
Etki/Risk
Severity
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
        module.send_message = safe_send_message
        _bot_module = module
        logging.info("0xVault Telegram webhook app loaded version=%s", getattr(module, "APP_VERSION", "unknown"))
        return module
    except Exception as exc:
        raise RuntimeError(f"main.py GitHub raw kaynagindan yuklenemedi: {exc}") from exc


def telegram_form(method, payload, retries=3):
    data = urllib.parse.urlencode(payload, doseq=True).encode("utf-8")
    headers = {"Content-Type": "application/x-www-form-urlencoded; charset=utf-8"}
    request = urllib.request.Request(f"{TELEGRAM_API_BASE}/{method}", data=data, headers=headers, method="POST")
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                body = response.read().decode("utf-8", errors="replace")
                return json.loads(body)
        except Exception as exc:
            last_error = exc
            logging.warning("Telegram form API error method=%s attempt=%s/%s error=%s", method, attempt, retries, exc)
            time.sleep(min(6, attempt * 2))
    logging.error("Telegram form API failed method=%s error=%s", method, last_error)
    return {"ok": False, "error": str(last_error)}


def safe_send_message(chat_id, text, reply_to=None):
    text = (text or "Tamam.").strip() or "Tamam."
    chunks = []
    while len(text) > 3900:
        split_at = text.rfind("\n", 0, 3900)
        if split_at < 1500:
            split_at = 3900
        chunks.append(text[:split_at].strip())
        text = text[split_at:].strip()
    if text:
        chunks.append(text)
    for chunk in chunks:
        payload = {
            "chat_id": chat_id,
            "text": chunk,
            "disable_web_page_preview": "true",
        }
        if reply_to:
            payload["reply_to_message_id"] = reply_to
        telegram_form("sendMessage", payload, retries=3)


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
        "text": (text or "OK").strip() or "OK",
        "disable_web_page_preview": True,
    }
    if reply_to:
        payload["reply_to_message_id"] = reply_to
    return payload


def ack_text(command):
    if command == "/chat":
        return "Istek alindi, isleniyor. Sonuc birazdan gonderilecek."
    if command == "/report":
        return "Istek alindi, gorsel ve rapor bilgileri isleniyor."
    return "Istek alindi."


def run_background(bot, message):
    try:
        bot.send_message = safe_send_message
        bot.handle_message(message)
    except Exception:
        logging.exception("background bot handling failed")
        chat_id = (message.get("chat") or {}).get("id")
        msg_id = message.get("message_id")
        if chat_id:
            safe_send_message(chat_id, "Islem sirasinda hata olustu. Lutfen tekrar dene.", msg_id)


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
        return webhook_method(chat_id, "Su an rapor modundasin. /tr, /en, /cancel veya /exitreport kullan.", msg_id)

    if command == "/help":
        return webhook_method(chat_id, ASCII_HELP, msg_id)

    if command == "/cancel":
        bot.clear_user(user_id)
        return webhook_method(chat_id, "Iptal edildi. Aktif islem durduruldu.", msg_id)

    if command == "/exitreport":
        if state.get(bot.REPORT_AWAITING_LANGUAGE) or state.get(bot.REPORT_PENDING_TEXT) or state.get(bot.REPORT_MODE):
            state.pop(bot.REPORT_MODE, None)
            state.pop(bot.REPORT_DRAFT, None)
            state.pop(bot.REPORT_AWAITING_LANGUAGE, None)
            state.pop(bot.REPORT_PENDING_TEXT, None)
            state.pop(bot.REPORT_PENDING_ANALYSIS, None)
            state.pop(bot.REPORT_PENDING_IMAGE_NOTE, None)
            return webhook_method(chat_id, "Rapor modundan cikildi.", msg_id)
        return webhook_method(chat_id, "Aktif rapor modu yok.", msg_id)

    if command == "/report" and not args:
        return webhook_method(chat_id, ASCII_REPORT_USAGE, msg_id)

    if command == "/report" and args and not message.get("photo"):
        allowed, retry = bot.allow_rate(user_id, "report", bot.REPORT_RATE_LIMIT_COUNT, bot.REPORT_RATE_LIMIT_WINDOW_SECONDS)
        if not allowed:
            return webhook_method(chat_id, f"Rapor uretim limiti asildi. {retry} saniye sonra tekrar dene.", msg_id)
        analysis = bot.analyze_report(args.strip())
        if not analysis["complete"]:
            return webhook_method(chat_id, bot.missing_message(analysis["missing"]), msg_id)
        state[bot.REPORT_PENDING_TEXT] = args.strip()
        state[bot.REPORT_PENDING_ANALYSIS] = analysis
        state[bot.REPORT_PENDING_IMAGE_NOTE] = ""
        state[bot.REPORT_AWAITING_LANGUAGE] = True
        return webhook_method(chat_id, "Rapor dili sec: /tr Turkce veya /en English", msg_id)

    if command in {"/tr", "/en"}:
        if not state.get(bot.REPORT_AWAITING_LANGUAGE):
            return webhook_method(chat_id, "Bekleyen rapor yok. Once /report <sorunu anlat> yaz.", msg_id)
        Thread(target=run_background, args=(bot, message), daemon=True).start()
        return webhook_method(chat_id, "Rapor hazirlaniyor. Sonuc birazdan gonderilecek.", msg_id)

    if command in {"/chat", "/report"}:
        Thread(target=run_background, args=(bot, message), daemon=True).start()
        return webhook_method(chat_id, ack_text(command), msg_id)

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
        "mode": "telegram_webhook_ascii_ack_form_send",
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
