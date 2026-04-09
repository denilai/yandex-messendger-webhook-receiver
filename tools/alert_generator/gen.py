from __future__ import annotations

import argparse
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _rfc3339(dt: datetime) -> str:
    # Alertmanager accepts RFC3339. Using Z suffix.
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _build_alert(i: int, *, mode: str, status: str, target: str, group_key: str) -> dict[str, Any]:
    starts = _now() - timedelta(minutes=1)
    if status == "resolved":
        ends = _now() - timedelta(seconds=5)
    else:
        ends = _now() + timedelta(hours=1)

    if mode == "burst":
        alertname = group_key
        instance = f"inst-{i}"
    elif mode == "spray":
        alertname = f"{group_key}-{i}"
        instance = f"inst-{i}"
    else:  # single
        alertname = group_key
        instance = "inst-0"

    labels = {
        "alertname": alertname,
        "severity": "critical" if (i % 5 == 0) else "warning",
        "job": "demo",
        "instance": instance,
        "am_target": target,
    }

    annotations = {
        "summary": f"{alertname} on {instance}",
        "description": f"Generated alert {i} in mode={mode}, target={target}, status={status}",
    }

    return {
        "labels": labels,
        "annotations": annotations,
        "startsAt": _rfc3339(starts),
        "endsAt": _rfc3339(ends),
        "generatorURL": "http://generator.local/example",
    }


def main() -> None:
    p = argparse.ArgumentParser(description="Generate alerts into Alertmanager /api/v2/alerts")
    p.add_argument("--url", default=os.getenv("ALERTMANAGER_URL", "http://localhost:9093"), help="Alertmanager base URL")
    p.add_argument("--mode", choices=["single", "burst", "spray"], default="single")
    p.add_argument("--count", type=int, default=1)
    p.add_argument("--target", choices=["chat", "user"], default="chat", help="Route matcher am_target")
    p.add_argument("--status", choices=["firing", "resolved"], default="firing")
    p.add_argument("--group-key", default="HighErrorRate", help="Base alertname (and group key for burst)")
    args = p.parse_args()

    n = max(1, int(args.count))
    alerts = [_build_alert(i, mode=args.mode, status=args.status, target=args.target, group_key=args.group_key) for i in range(n)]

    api = args.url.rstrip("/") + "/api/v2/alerts"
    with httpx.Client(timeout=5.0) as client:
        r = client.post(api, json=alerts)
        r.raise_for_status()
        # Alertmanager returns 200/202 with empty body typically.
        print(f"sent {len(alerts)} alerts -> {r.status_code}")


if __name__ == "__main__":
    main()

