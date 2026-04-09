from __future__ import annotations

import hashlib
from dataclasses import dataclass

import httpx

from app.config.settings import Settings
from app.models.alertmanager import AlertmanagerWebhookV4
from app.models.yandex import YandexSendTextRequest, YandexSendTextResponse


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
        headers = {
            "Authorization": f"OAuth {self._settings.yandex_oauth_token}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout()) as client:
                resp = await client.post(
                    self._url(),
                    headers=headers,
                    json=req.model_dump(by_alias=True, exclude_none=True),
                )
        except (httpx.TimeoutException, httpx.NetworkError) as e:
            raise YandexTemporaryError(str(e)) from e

        if resp.status_code in (429,) or 500 <= resp.status_code <= 599:
            raise YandexTemporaryError(f"Yandex returned {resp.status_code}")

        if 400 <= resp.status_code <= 499:
            raise YandexPermanentError(f"Yandex returned {resp.status_code}: {resp.text}")

        try:
            data = YandexSendTextResponse.model_validate(resp.json())
        except Exception as e:  # noqa: BLE001
            # Unknown response format is treated as temporary to let Alertmanager retry.
            raise YandexTemporaryError(f"Invalid Yandex response: {e}") from e

        if not data.ok:
            # If API returns ok=false with 2xx, treat it as permanent (policy decision)
            raise YandexPermanentError("Yandex response ok=false")

        return YandexSendResult(ok=True, message_id=data.message_id)

