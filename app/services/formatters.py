from __future__ import annotations

from collections.abc import Iterable

from app.models.alertmanager import AlertmanagerWebhookV4


MAX_TEXT_LEN = 6000
TRUNCATION_SUFFIX = "\n\n… (truncated to 6000 chars)"


def _fmt_kv(d: dict[str, str]) -> str:
    if not d:
        return "-"
    parts = [f"{k}={d[k]}" for k in sorted(d.keys())]
    return ", ".join(parts)


def _first_non_empty(*values: str | None) -> str | None:
    for v in values:
        if v is not None and str(v).strip() != "":
            return v
    return None


def _lines(items: Iterable[str]) -> str:
    return "\n".join(items)


def render_alertmanager_text(payload: AlertmanagerWebhookV4, *, max_alerts: int = 5) -> str:
    status_upper = payload.status.upper()

    alertname = _first_non_empty(
        payload.commonLabels.get("alertname"),
        payload.alerts[0].labels.get("alertname") if payload.alerts else None,
        "ALERT",
    )

    summary = _first_non_empty(
        payload.commonAnnotations.get("summary"),
        payload.alerts[0].annotations.get("summary") if payload.alerts else None,
    )
    description = _first_non_empty(
        payload.commonAnnotations.get("description"),
        payload.alerts[0].annotations.get("description") if payload.alerts else None,
    )

    firing = sum(1 for a in payload.alerts if a.status == "firing")
    resolved = sum(1 for a in payload.alerts if a.status == "resolved")

    header = f"[{status_upper}] {alertname}  ({firing} firing / {resolved} resolved)"

    blocks: list[str] = [header, ""]
    if summary is not None:
        blocks.append(f"Summary: {summary}")
    if description is not None:
        blocks.append(f"Description: {description}")

    blocks.extend(
        [
            "",
            f"Group: {_fmt_kv(payload.groupLabels)}",
            f"Common: {_fmt_kv(payload.commonLabels)}",
            "",
            "Alerts:",
        ]
    )

    shown = payload.alerts[: max(0, max_alerts)]
    for a in shown:
        inst = a.labels.get("instance", "?")
        job = a.labels.get("job", "?")
        sev = a.labels.get("severity", "?")
        blocks.append(f"- {inst} {job} {sev}")
        blocks.append(f"  startsAt={a.startsAt.isoformat()} endsAt={a.endsAt.isoformat()}")

        a_summary = _first_non_empty(a.annotations.get("summary"))
        if a_summary is not None:
            blocks.append(f"  {a_summary}")
        if a.generatorURL:
            blocks.append(f"  {a.generatorURL}")

    remaining = max(0, len(payload.alerts) - len(shown))
    extra_trunc = max(0, payload.truncatedAlerts)
    if remaining or extra_trunc:
        blocks.append(f"… (+{remaining + extra_trunc} more)")

    blocks.extend(
        [
            "",
            f"Alertmanager: {payload.externalURL or '-'}",
            f"GroupKey: {payload.groupKey}",
        ]
    )

    text = _lines(blocks).strip()
    if len(text) <= MAX_TEXT_LEN:
        return text

    keep = MAX_TEXT_LEN - len(TRUNCATION_SUFFIX)
    if keep <= 0:
        return TRUNCATION_SUFFIX[-MAX_TEXT_LEN:]
    return text[:keep] + TRUNCATION_SUFFIX

