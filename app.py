import importlib.util
import logging
import os
import sys
import tempfile
import urllib.request

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


def process_update_with_webhook_response(update):
    bot = load_remote_main()
    responses = []

    def capture_send_message(chat_id, text, reply_to=None):
        text = (text or "Tamam.").strip() or "Tamam."
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
        responses.append(payload)

    bot.send_message = capture_send_message
    message = update.get("message") if isinstance(update, dict) else None
    if message:
        bot.handle_message(message)
    if responses:
        return responses[0]
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
        "mode": "telegram_webhook",
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
        result = process_update_with_webhook_response(update)
        return JSONResponse(result)
    except Exception as exc:
        logging.exception("telegram webhook failed")
        return JSONResponse({"ok": True, "error": str(exc)})
