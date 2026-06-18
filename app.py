import logging
from threading import Thread
from fastapi import FastAPI

import main

app = FastAPI()
_started = False
_startup_error = ""


def run_bot_once() -> None:
    global _started, _startup_error
    if _started:
        return
    if not hasattr(main, "poll_loop"):
        _startup_error = "main.py içinde poll_loop fonksiyonu yok. Hugging Face'teki main.py eski veya yanlış dosya."
        logging.error(_startup_error)
        return
    if hasattr(main, "validate_config"):
        try:
            main.validate_config()
        except Exception as exc:
            _startup_error = f"Config hatası: {exc}"
            logging.error(_startup_error)
            return
    else:
        missing = []
        if not getattr(main, "TELEGRAM_BOT_TOKEN", ""):
            missing.append("TELEGRAM_BOT_TOKEN")
        if not getattr(main, "GEMINI_API_KEY", ""):
            missing.append("GEMINI_API_KEY")
        if missing:
            _startup_error = "Eksik secret/env: " + ", ".join(missing)
            logging.error(_startup_error)
            return
    _started = True
    Thread(target=main.poll_loop, daemon=True).start()
    logging.info("0xVault Telegram polling thread started version=%s", getattr(main, "APP_VERSION", "unknown"))


@app.on_event("startup")
def startup_event() -> None:
    run_bot_once()


@app.get("/")
def root() -> dict[str, str]:
    return {
        "status": "ok" if _started else "bot_not_started",
        "service": "0xVault Telegram Bot",
        "version": getattr(main, "APP_VERSION", "unknown"),
        "error": _startup_error,
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "bot_started": str(_started), "error": _startup_error}
