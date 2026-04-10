from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.alerts import router as v1_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title="alertmanager-yandex-receiver", version="0.1.0", lifespan=lifespan)
app.include_router(v1_router)


@app.get("/healthz")
def healthz() -> dict[str, bool]:
    return {"ok": True}

