from __future__ import annotations

import logging
import pathlib
from typing import TYPE_CHECKING

import jinja2

from app.metrics import RENDER_FAILURES_TOTAL
from app.models.alertmanager import AlertmanagerAlertV4, AlertmanagerWebhookV4

if TYPE_CHECKING:
    from app.config.settings import Settings


logger = logging.getLogger(__name__)

MAX_TEXT_LEN = 6000
TRUNCATION_SUFFIX = "\n\n… (truncated to 6000 chars)"
MAX_ALERTS_DEFAULT = 5

_BUILTIN_TEMPLATES_DIR = pathlib.Path(__file__).parent.parent / "templates"


def _fmt_kv(d: dict[str, str]) -> str:
    if not d:
        return "-"
    return ", ".join(f"{k}={d[k]}" for k in sorted(d.keys()))


def _first_non_empty(*values: str | None) -> str | None:
    for v in values:
        if v is not None and str(v).strip() != "":
            return v
    return None


def _slice_alerts(alerts: list[AlertmanagerAlertV4], n: int) -> list[AlertmanagerAlertV4]:
    return alerts[: max(0, n)]


def _build_jinja_env(extra_path: pathlib.Path | None = None) -> jinja2.Environment:
    loaders: list[jinja2.BaseLoader] = [jinja2.FileSystemLoader(str(_BUILTIN_TEMPLATES_DIR))]
    if extra_path is not None:
        loaders.insert(0, jinja2.FileSystemLoader(str(extra_path)))

    env = jinja2.Environment(
        loader=jinja2.ChoiceLoader(loaders),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=False,
        undefined=jinja2.StrictUndefined,
    )
    env.filters["kv"] = _fmt_kv
    env.filters["slice_alerts"] = _slice_alerts
    return env


def _build_context(payload: AlertmanagerWebhookV4, max_alerts: int) -> dict[str, object]:
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
    shown = max(0, min(max_alerts, len(payload.alerts)))
    overflow = max(0, len(payload.alerts) - shown) + max(0, payload.truncatedAlerts)

    return {
        "status": payload.status,
        "groupKey": payload.groupKey,
        "receiver": payload.receiver,
        "truncatedAlerts": payload.truncatedAlerts,
        "groupLabels": payload.groupLabels,
        "commonLabels": payload.commonLabels,
        "commonAnnotations": payload.commonAnnotations,
        "externalURL": payload.externalURL,
        "alerts": payload.alerts,
        "alertname": alertname,
        "summary": summary,
        "description": description,
        "firing": firing,
        "resolved": resolved,
        "max_alerts": max_alerts,
        "overflow": overflow,
    }


def _truncate(text: str) -> str:
    if len(text) <= MAX_TEXT_LEN:
        return text
    keep = MAX_TEXT_LEN - len(TRUNCATION_SUFFIX)
    if keep <= 0:
        return TRUNCATION_SUFFIX[-MAX_TEXT_LEN:]
    return text[:keep] + TRUNCATION_SUFFIX


def render_alertmanager_text(
    payload: AlertmanagerWebhookV4,
    *,
    settings: Settings | None = None,
    max_alerts: int = MAX_ALERTS_DEFAULT,
) -> str:
    context = _build_context(payload, max_alerts)

    inline = settings.message_template if settings else None
    file_path = settings.message_template_file if settings else None

    try:
        if inline:
            tmpl = jinja2.Environment(
                autoescape=False,
                trim_blocks=True,
                lstrip_blocks=True,
                keep_trailing_newline=False,
                undefined=jinja2.StrictUndefined,
            )
            tmpl.filters["kv"] = _fmt_kv
            tmpl.filters["slice_alerts"] = _slice_alerts
            text = tmpl.from_string(inline).render(**context)
        elif file_path:
            p = pathlib.Path(file_path)
            env = _build_jinja_env(extra_path=p.parent)
            text = env.get_template(p.name).render(**context)
        else:
            env = _build_jinja_env()
            text = env.get_template("default.j2").render(**context)
    except jinja2.TemplateError as exc:
        logger.error("Template rendering failed, falling back to plain format: %s", exc)
        RENDER_FAILURES_TOTAL.inc()
        text = _plain_fallback(payload)

    return _truncate(text.strip())


def _plain_fallback(payload: AlertmanagerWebhookV4) -> str:
    status_upper = payload.status.upper()
    alertname = _first_non_empty(
        payload.commonLabels.get("alertname"),
        payload.alerts[0].labels.get("alertname") if payload.alerts else None,
        "ALERT",
    )
    firing = sum(1 for a in payload.alerts if a.status == "firing")
    resolved = sum(1 for a in payload.alerts if a.status == "resolved")
    lines = [
        f"[{status_upper}] {alertname}  ({firing} firing / {resolved} resolved)",
        f"GroupKey: {payload.groupKey}",
    ]
    return "\n".join(lines)

