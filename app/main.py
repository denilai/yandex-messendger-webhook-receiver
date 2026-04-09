from __future__ import annotations

from fastapi import FastAPI

from app.api.v1.alerts import router as v1_router

app = FastAPI(title="alertmanager-yandex-receiver", version="0.1.0")
app.include_router(v1_router)


@app.get("/healthz")
def healthz() -> dict[str, bool]:
    return {"ok": True}

