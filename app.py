import logging
from threading import Thread
from fastapi import FastAPI

import main

app = FastAPI()
_started = False


def run_bot_once() -> None:
    global _started
    if _started:
        return
    _started = True
    main.validate_config()
    Thread(target=main.poll_loop, daemon=True).start()
    logging.info("0xVault Telegram polling thread started")


@app.on_event("startup")
def startup_event() -> None:
    run_bot_once()


@app.get("/")
def root() -> dict[str, str]:
    return {"status": "ok", "service": "0xVault Telegram Bot", "version": main.APP_VERSION}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
