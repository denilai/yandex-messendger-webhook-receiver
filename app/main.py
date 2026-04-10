from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.alerts import router as v1_router
from app.config.logging import setup_logging
from app.config.settings import get_settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings.log_level, settings.log_format, settings.log_config)
    logger.info("Service started", extra={"version": app.version})
    yield


app = FastAPI(title="alertmanager-yandex-receiver", version="0.1.0", lifespan=lifespan)
app.include_router(v1_router)


@app.get("/healthz")
def healthz() -> dict[str, bool]:
    return {"ok": True}

