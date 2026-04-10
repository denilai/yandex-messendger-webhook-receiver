from __future__ import annotations

import os

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from prometheus_client import Gauge

WEBHOOK_REQUESTS_TOTAL = Counter(
    "receiver_webhook_requests_total",
    "Incoming webhook requests.",
    ["target", "payload_status"],
)

WEBHOOK_ALERTS_TOTAL = Counter(
    "receiver_webhook_alerts_total",
    "Total number of alerts received in webhook payloads.",
    ["target", "payload_status"],
)

RENDER_FAILURES_TOTAL = Counter(
    "receiver_render_failures_total",
    "Template render failures with fallback.",
)

YANDEX_SEND_TOTAL = Counter(
    "receiver_yandex_send_total",
    "Yandex sendText outcomes.",
    ["target", "outcome"],
)

YANDEX_SEND_LATENCY_SECONDS = Histogram(
    "receiver_yandex_send_latency_seconds",
    "Latency of Yandex sendText calls.",
    ["target", "outcome"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10),
)

RECEIVER_WORKERS_CONFIGURED = Gauge(
    "receiver_workers_configured",
    "Configured number of Uvicorn workers for receiver process.",
)
try:
    _workers = int(os.getenv("UVICORN_WORKERS", "1"))
except ValueError:
    _workers = 1
RECEIVER_WORKERS_CONFIGURED.set(_workers)


def metrics_payload() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
