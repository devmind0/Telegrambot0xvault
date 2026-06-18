import importlib.util
import logging
import os
import sys
import tempfile
import urllib.request
from threading import Thread

from fastapi import FastAPI

RAW_MAIN_URL = os.getenv(
    "BOT_MAIN_URL",
    "https://raw.githubusercontent.com/devmind0/Telegrambot0xvault/main/main.py",
)

app = FastAPI()
_started = False
_startup_error = ""
_bot_module = None


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
        _bot_module = module
        return module
    except Exception as exc:
        raise RuntimeError(f"main.py GitHub raw kaynağından yüklenemedi: {exc}") from exc


def start_bot_once():
    global _started, _startup_error
    if _started:
        return
    try:
        bot = load_remote_main()
        bot.validate_config()
        Thread(target=bot.poll_loop, daemon=True).start()
        _started = True
        logging.info("0xVault Telegram bot started version=%s", getattr(bot, "APP_VERSION", "unknown"))
    except Exception as exc:
        _startup_error = str(exc)
        logging.exception("0xVault Telegram bot startup failed")


@app.on_event("startup")
def startup_event():
    start_bot_once()


@app.get("/")
def root():
    version = "unknown"
    if _bot_module is not None:
        version = getattr(_bot_module, "APP_VERSION", "unknown")
    return {
        "status": "ok" if _started else "bot_not_started",
        "service": "0xVault Telegram Bot",
        "version": version,
        "error": _startup_error,
    }


@app.get("/health")
def health():
    return {"status": "ok", "bot_started": _started, "error": _startup_error}
