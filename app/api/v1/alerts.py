from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.basic import require_basic_auth
from app.config.settings import Settings, get_settings
from app.metrics import WEBHOOK_ALERTS_TOTAL, WEBHOOK_REQUESTS_TOTAL
from app.models.alertmanager import AlertmanagerWebhookV4
from app.services.formatters import render_alertmanager_text
from app.services.yandex_client import (
    YandexClient,
    YandexPermanentError,
    YandexTemporaryError,
    build_payload_id,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["alerts"])


def _client(settings: Settings) -> YandexClient:
    return YandexClient(settings)


def _accepted(ok: bool, message_id: int | None) -> dict[str, object]:
    return {"ok": ok, "yandex_message_id": message_id}


@router.post("/alerts/users/{login}", status_code=status.HTTP_202_ACCEPTED)
async def post_alerts_user(
    login: str,
    payload: AlertmanagerWebhookV4,
    _auth: None = Depends(require_basic_auth),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    text = render_alertmanager_text(payload, settings=settings)
    payload_id = build_payload_id(payload, target_kind="login", target_value=login, text=text)
    alert_count = len(payload.alerts)
    WEBHOOK_REQUESTS_TOTAL.labels(target="user", payload_status=payload.status).inc()
    WEBHOOK_ALERTS_TOTAL.labels(target="user", payload_status=payload.status).inc(alert_count)
    logger.info(
        "Webhook received: target=user login=%s payload_id=%s alerts=%d status=%s",
        login,
        payload_id,
        alert_count,
        payload.status,
    )
    client = _client(settings)

    try:
        res = await client.send_text(text=text, login=login, chat_id=None, payload_id=payload_id)
        logger.info("Message delivered: target=user login=%s payload_id=%s message_id=%s", login, payload_id, res.message_id)
        return _accepted(True, res.message_id)
    except YandexTemporaryError as e:
        logger.error("Yandex temporary error: target=user login=%s payload_id=%s error=%s", login, payload_id, e)
        raise HTTPException(status_code=503, detail=str(e)) from e
    except YandexPermanentError as e:
        if settings.fail_on_yandex_4xx:
            logger.error("Yandex permanent error: target=user login=%s payload_id=%s error=%s", login, payload_id, e)
            raise HTTPException(status_code=422, detail=str(e)) from e
        logger.warning("Yandex permanent error (ignored): target=user login=%s payload_id=%s error=%s", login, payload_id, e)
        return _accepted(False, None)


@router.post("/alerts/chats/{chat_id}", status_code=status.HTTP_202_ACCEPTED)
async def post_alerts_chat(
    chat_id: str,
    payload: AlertmanagerWebhookV4,
    _auth: None = Depends(require_basic_auth),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    text = render_alertmanager_text(payload, settings=settings)
    payload_id = build_payload_id(payload, target_kind="chat_id", target_value=chat_id, text=text)
    alert_count = len(payload.alerts)
    WEBHOOK_REQUESTS_TOTAL.labels(target="chat", payload_status=payload.status).inc()
    WEBHOOK_ALERTS_TOTAL.labels(target="chat", payload_status=payload.status).inc(alert_count)
    logger.info(
        "Webhook received: target=chat chat_id=%s payload_id=%s alerts=%d status=%s",
        chat_id,
        payload_id,
        alert_count,
        payload.status,
    )
    client = _client(settings)

    try:
        res = await client.send_text(text=text, login=None, chat_id=chat_id, payload_id=payload_id)
        logger.info(
            "Message delivered: target=chat chat_id=%s payload_id=%s message_id=%s",
            chat_id,
            payload_id,
            res.message_id,
        )
        return _accepted(True, res.message_id)
    except YandexTemporaryError as e:
        logger.error("Yandex temporary error: target=chat chat_id=%s payload_id=%s error=%s", chat_id, payload_id, e)
        raise HTTPException(status_code=503, detail=str(e)) from e
    except YandexPermanentError as e:
        if settings.fail_on_yandex_4xx:
            logger.error("Yandex permanent error: target=chat chat_id=%s payload_id=%s error=%s", chat_id, payload_id, e)
            raise HTTPException(status_code=422, detail=str(e)) from e
        logger.warning("Yandex permanent error (ignored): target=chat chat_id=%s payload_id=%s error=%s", chat_id, payload_id, e)
        return _accepted(False, None)

