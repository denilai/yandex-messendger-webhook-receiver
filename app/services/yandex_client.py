from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

import httpx

from app.config.settings import Settings
from app.models.alertmanager import AlertmanagerWebhookV4
from app.models.yandex import YandexSendTextRequest, YandexSendTextResponse


logger = logging.getLogger(__name__)


class YandexTemporaryError(RuntimeError):
    pass


class YandexPermanentError(RuntimeError):
    pass


@dataclass(frozen=True)
class YandexSendResult:
    ok: bool
    message_id: int | None = None


def build_payload_id(payload: AlertmanagerWebhookV4) -> str:
    raw = f"{payload.groupKey}|{payload.status}|{payload.receiver}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class YandexClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _url(self) -> str:
        base = self._settings.yandex_api_base.rstrip("/")
        # Per research/docs: message-send-text → sendText
        return f"{base}/bot/v1/messages/sendText"

    def _timeout(self) -> httpx.Timeout:
        t = float(self._settings.yandex_http_timeout_seconds)
        return httpx.Timeout(timeout=t)

    async def send_text(
        self,
        *,
        text: str,
        login: str | None,
        chat_id: str | None,
        payload_id: str | None,
    ) -> YandexSendResult:
        req = YandexSendTextRequest(text=text, login=login, chat_id=chat_id, payload_id=payload_id)
        url = self._url()
        headers = {"Authorization": f"OAuth {self._settings.yandex_oauth_token}", "Content-Type": "application/json"}
        body = req.model_dump(by_alias=True, exclude_none=True)

        logger.debug("Sending request to Yandex: POST %s body=%s", url, body)

        try:
            async with httpx.AsyncClient(timeout=self._timeout()) as client:
                resp = await client.post(
                    url,
                    headers=headers,
                    json=body,
                )
        except (httpx.TimeoutException, httpx.NetworkError) as e:
            logger.warning("Yandex network/timeout error: %s", e)
            raise YandexTemporaryError(str(e)) from e

        if resp.status_code in (429,) or 500 <= resp.status_code <= 599:
            logger.warning("Yandex returned server error: %d", resp.status_code)
            raise YandexTemporaryError(f"Yandex returned {resp.status_code}")

        if 400 <= resp.status_code <= 499:
            logger.warning("Yandex returned client error: %d %s", resp.status_code, resp.text)
            raise YandexPermanentError(f"Yandex returned {resp.status_code}: {resp.text}")

        try:
            data = YandexSendTextResponse.model_validate(resp.json())
        except Exception as e:  # noqa: BLE001
            logger.warning("Invalid Yandex response format: %s", e)
            raise YandexTemporaryError(f"Invalid Yandex response: {e}") from e

        if not data.ok:
            logger.warning("Yandex response ok=false")
            raise YandexPermanentError("Yandex response ok=false")

        logger.debug("Yandex response OK: %d message_id=%s", resp.status_code, data.message_id)
        return YandexSendResult(ok=True, message_id=data.message_id)

