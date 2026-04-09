from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from jinja2 import TemplateError

from app.auth.basic import require_basic_auth
from app.config.settings import Settings, get_settings
from app.models.alertmanager import AlertmanagerWebhookV4
from app.services.formatters import render_alertmanager_text
from app.services.templating import Target, try_render_message_template
from app.services.yandex_client import (
    YandexClient,
    YandexPermanentError,
    YandexTemporaryError,
    build_payload_id,
)

router = APIRouter(prefix="/v1", tags=["alerts"])


def _client(settings: Settings) -> YandexClient:
    return YandexClient(settings)


def _accepted(ok: bool, message_id: int | None) -> dict[str, object]:
    return {"ok": ok, "yandex_message_id": message_id}


def _templates_dir() -> str:
    # app/api/v1/alerts.py -> app/
    app_dir = Path(__file__).resolve().parents[2]
    return str(app_dir / "templates")


def _render_text(payload: AlertmanagerWebhookV4, *, settings: Settings, target: Target) -> str:
    try:
        used, text = try_render_message_template(
            payload=payload,
            target=target,
            template_name=settings.message_template_name,
            template_inline=settings.message_template_inline,
            max_alerts=settings.message_template_max_alerts,
            templates_dir=_templates_dir(),
        )
    except TemplateError:
        # Keep delivery working even if template is broken.
        return render_alertmanager_text(payload)

    return text if used else render_alertmanager_text(payload)


@router.post("/alerts/users/{login}", status_code=status.HTTP_202_ACCEPTED)
async def post_alerts_user(
    login: str,
    payload: AlertmanagerWebhookV4,
    _auth: None = Depends(require_basic_auth),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    text = _render_text(payload, settings=settings, target=Target(type="user", login=login))
    client = _client(settings)
    payload_id = build_payload_id(payload)

    try:
        res = await client.send_text(text=text, login=login, chat_id=None, payload_id=payload_id)
        return _accepted(True, res.message_id)
    except YandexTemporaryError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except YandexPermanentError as e:
        if settings.fail_on_yandex_4xx:
            raise HTTPException(status_code=422, detail=str(e)) from e
        return _accepted(False, None)


@router.post("/alerts/chats/{chat_id}", status_code=status.HTTP_202_ACCEPTED)
async def post_alerts_chat(
    chat_id: str,
    payload: AlertmanagerWebhookV4,
    _auth: None = Depends(require_basic_auth),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    text = _render_text(payload, settings=settings, target=Target(type="chat", chat_id=chat_id))
    client = _client(settings)
    payload_id = build_payload_id(payload)

    try:
        res = await client.send_text(text=text, login=None, chat_id=chat_id, payload_id=payload_id)
        return _accepted(True, res.message_id)
    except YandexTemporaryError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except YandexPermanentError as e:
        if settings.fail_on_yandex_4xx:
            raise HTTPException(status_code=422, detail=str(e)) from e
        return _accepted(False, None)

