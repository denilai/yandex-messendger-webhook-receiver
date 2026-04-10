from __future__ import annotations

import argparse
import asyncio
import math
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any

import httpx


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    if p <= 0:
        return min(values)
    if p >= 100:
        return max(values)
    s = sorted(values)
    idx = math.ceil((p / 100) * len(s)) - 1
    idx = max(0, min(idx, len(s) - 1))
    return s[idx]


def _build_payload(i: int, generated_at: datetime) -> dict[str, Any]:
    starts = generated_at - timedelta(minutes=1)
    ends = generated_at + timedelta(hours=1)
    alertname = f"LoadNoGroup-{i}"
    instance = f"load-inst-{i}"

    return {
        "version": "4",
        "groupKey": f"load-key-{i}",
        "truncatedAlerts": 0,
        "status": "firing",
        "receiver": "load-test",
        "groupLabels": {"alertname": alertname},
        "commonLabels": {"alertname": alertname, "severity": "warning", "job": "load"},
        "commonAnnotations": {
            "summary": f"{alertname} on {instance}",
            "description": f"receiver load test generated_at={_iso(generated_at)}",
        },
        "externalURL": "http://alertmanager.local",
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": alertname,
                    "severity": "warning",
                    "job": "load",
                    "instance": instance,
                    "am_target": "chat",
                },
                "annotations": {
                    "summary": f"{alertname} on {instance}",
                    "description": f"receiver load test generated_at={_iso(generated_at)}",
                },
                "startsAt": _iso(starts),
                "endsAt": _iso(ends),
                "generatorURL": "http://load.local/generator",
                "fingerprint": f"fp-load-{i}",
            }
        ],
    }


@dataclass
class Result:
    code: int
    latency_ms: float
    error: str | None = None


def _parse_prom_counter(text: str, metric_name: str) -> int:
    pattern = re.compile(rf"^{re.escape(metric_name)}\s+([0-9]+(?:\.[0-9]+)?)$")
    for line in text.splitlines():
        m = pattern.match(line.strip())
        if m:
            return int(float(m.group(1)))
    return 0


async def _mock_total_requests(client: httpx.AsyncClient, mock_base: str) -> int:
    r = await client.get(f"{mock_base.rstrip('/')}/metrics")
    r.raise_for_status()
    return _parse_prom_counter(r.text, "mock_yandex_send_text_total")


async def _single_send(
    client: httpx.AsyncClient,
    *,
    receiver_url: str,
    request_id: int,
) -> Result:
    payload = _build_payload(request_id, datetime.now(timezone.utc))
    start = time.perf_counter()
    try:
        resp = await client.post(receiver_url, json=payload)
        elapsed_ms = (time.perf_counter() - start) * 1000
        return Result(code=resp.status_code, latency_ms=elapsed_ms)
    except Exception as exc:  # noqa: BLE001
        elapsed_ms = (time.perf_counter() - start) * 1000
        return Result(code=0, latency_ms=elapsed_ms, error=str(exc))


async def _run_load(
    *,
    receiver_url: str,
    username: str,
    password: str,
    rps: float,
    duration_s: float,
    mock_base: str,
) -> int:
    auth = (username, password)
    timeout = httpx.Timeout(10.0)
    limits = httpx.Limits(max_connections=1000, max_keepalive_connections=200)

    async with httpx.AsyncClient(auth=auth, timeout=timeout, limits=limits) as client:
        before_count = await _mock_total_requests(client, mock_base)

        total_requests = int(max(1, round(rps * duration_s)))
        interval = 1.0 / max(rps, 0.001)
        tasks: list[asyncio.Task[Result]] = []

        started = time.perf_counter()
        for i in range(total_requests):
            target_t = started + i * interval
            now = time.perf_counter()
            delay = target_t - now
            if delay > 0:
                await asyncio.sleep(delay)
            tasks.append(asyncio.create_task(_single_send(client, receiver_url=receiver_url, request_id=i)))

        results = await asyncio.gather(*tasks)
        elapsed_total = time.perf_counter() - started

        after_count = await _mock_total_requests(client, mock_base)
        delivered_delta = max(0, after_count - before_count)

    ok_202 = [r for r in results if r.code == 202]
    non_202 = [r for r in results if r.code != 202 and r.error is None]
    transport_errors = [r for r in results if r.error is not None]
    lat_all = [r.latency_ms for r in results]
    lat_ok = [r.latency_ms for r in ok_202]

    print("=== Receiver load test report ===")
    print(f"receiver_url:      {receiver_url}")
    print(f"sent_requests:     {len(results)}")
    print(f"duration_sec:      {elapsed_total:.2f}")
    print(f"achieved_rps:      {len(results) / max(elapsed_total, 0.001):.2f}")
    print(f"accepted_202:      {len(ok_202)}")
    print(f"http_non_202:      {len(non_202)}")
    print(f"transport_errors:  {len(transport_errors)}")
    print(f"delivered_to_mock: {delivered_delta}")
    print(f"delivery_gap:      {len(ok_202) - delivered_delta}")
    print("")
    print("--- latency all requests (ms) ---")
    print(f"min: {min(lat_all) if lat_all else 0:.2f}")
    print(f"p50: {_percentile(lat_all, 50):.2f}")
    print(f"p95: {_percentile(lat_all, 95):.2f}")
    print(f"p99: {_percentile(lat_all, 99):.2f}")
    print(f"max: {max(lat_all) if lat_all else 0:.2f}")
    print(f"avg: {(sum(lat_all) / len(lat_all)) if lat_all else 0:.2f}")
    print(f"med: {median(lat_all) if lat_all else 0:.2f}")
    print("")
    print("--- latency accepted(202) only (ms) ---")
    print(f"p50: {_percentile(lat_ok, 50):.2f}")
    print(f"p95: {_percentile(lat_ok, 95):.2f}")
    print(f"p99: {_percentile(lat_ok, 99):.2f}")

    if transport_errors:
        print("")
        print("sample transport errors:")
        for item in transport_errors[:5]:
            print(f"- {item.error}")

    if len(ok_202) != delivered_delta:
        print("")
        print("WARNING: accepted_202 != delivered_to_mock")
        print("Check `docker compose logs receiver mock-yandex` for retries/errors.")
        return 2

    return 0


def main() -> None:
    p = argparse.ArgumentParser(description="Load test receiver and verify deliveries in mock-yandex")
    p.add_argument("--receiver-url", default="http://localhost:8081/v1/alerts/chats/123")
    p.add_argument("--username", default="user")
    p.add_argument("--password", default="pass")
    p.add_argument("--rps", type=float, default=50.0)
    p.add_argument("--duration", type=float, default=30.0, help="Duration in seconds")
    p.add_argument("--mock-base", default="http://localhost:18080")
    args = p.parse_args()

    exit_code = asyncio.run(
        _run_load(
            receiver_url=args.receiver_url,
            username=args.username,
            password=args.password,
            rps=args.rps,
            duration_s=args.duration,
            mock_base=args.mock_base,
        )
    )
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
