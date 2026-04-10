from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass

import httpx

from app.config.settings import Settings
from app.metrics import YANDEX_SEND_LATENCY_SECONDS, YANDEX_SEND_TOTAL
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


def build_payload_id(
    payload: AlertmanagerWebhookV4,
    *,
    target_kind: str,
    target_value: str,
    text: str,
) -> str:
    payload_canonical = json.dumps(
        payload.model_dump(mode="json", by_alias=True, exclude_none=False),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    raw = f"{target_kind}|{target_value}|{text}|{payload_canonical}"
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

        target = "user" if login else "chat"
        logger.info(
            "Sending message to Yandex: target=%s payload_id=%s",
            target,
            payload_id,
        )
        start = time.perf_counter()

        try:
            async with httpx.AsyncClient(timeout=self._timeout()) as client:
                resp = await client.post(
                    url,
                    headers=headers,
                    json=body,
                )
        except (httpx.TimeoutException, httpx.NetworkError) as e:
            elapsed = time.perf_counter() - start
            YANDEX_SEND_TOTAL.labels(target=target, outcome="transport_error").inc()
            YANDEX_SEND_LATENCY_SECONDS.labels(target=target, outcome="transport_error").observe(elapsed)
            logger.warning("Yandex network/timeout error: payload_id=%s error=%s", payload_id, e)
            raise YandexTemporaryError(str(e)) from e

        if resp.status_code in (429,) or 500 <= resp.status_code <= 599:
            elapsed = time.perf_counter() - start
            YANDEX_SEND_TOTAL.labels(target=target, outcome="temporary_error").inc()
            YANDEX_SEND_LATENCY_SECONDS.labels(target=target, outcome="temporary_error").observe(elapsed)
            logger.warning("Yandex temporary response: payload_id=%s status=%d", payload_id, resp.status_code)
            raise YandexTemporaryError(f"Yandex returned {resp.status_code}")

        if 400 <= resp.status_code <= 499:
            elapsed = time.perf_counter() - start
            YANDEX_SEND_TOTAL.labels(target=target, outcome="permanent_error").inc()
            YANDEX_SEND_LATENCY_SECONDS.labels(target=target, outcome="permanent_error").observe(elapsed)
            logger.warning(
                "Yandex permanent response: payload_id=%s status=%d body=%s",
                payload_id,
                resp.status_code,
                resp.text,
            )
            raise YandexPermanentError(f"Yandex returned {resp.status_code}: {resp.text}")

        try:
            data = YandexSendTextResponse.model_validate(resp.json())
        except Exception as e:  # noqa: BLE001
            elapsed = time.perf_counter() - start
            YANDEX_SEND_TOTAL.labels(target=target, outcome="invalid_response").inc()
            YANDEX_SEND_LATENCY_SECONDS.labels(target=target, outcome="invalid_response").observe(elapsed)
            logger.warning("Invalid Yandex response format: payload_id=%s error=%s", payload_id, e)
            raise YandexTemporaryError(f"Invalid Yandex response: {e}") from e

        if not data.ok:
            elapsed = time.perf_counter() - start
            YANDEX_SEND_TOTAL.labels(target=target, outcome="ok_false").inc()
            YANDEX_SEND_LATENCY_SECONDS.labels(target=target, outcome="ok_false").observe(elapsed)
            logger.warning("Yandex response ok=false: payload_id=%s", payload_id)
            raise YandexPermanentError("Yandex response ok=false")

        elapsed = time.perf_counter() - start
        YANDEX_SEND_TOTAL.labels(target=target, outcome="success").inc()
        YANDEX_SEND_LATENCY_SECONDS.labels(target=target, outcome="success").observe(elapsed)
        logger.info(
            "Yandex delivered: payload_id=%s status=%d message_id=%s",
            payload_id,
            resp.status_code,
            data.message_id,
        )
        return YandexSendResult(ok=True, message_id=data.message_id)

