from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from jinja2 import Environment, FileSystemLoader, TemplateError

from app.models.alertmanager import AlertmanagerWebhookV4
from app.services.formatters import MAX_TEXT_LEN, TRUNCATION_SUFFIX, _fmt_kv, _first_non_empty


@dataclass(frozen=True)
class Target:
    type: str  # "user" | "chat"
    login: str | None = None
    chat_id: str | None = None


def _truncate(text: str, max_len: int = MAX_TEXT_LEN) -> str:
    if len(text) <= max_len:
        return text
    keep = max_len - len(TRUNCATION_SUFFIX)
    if keep <= 0:
        return TRUNCATION_SUFFIX[-max_len:]
    return text[:keep] + TRUNCATION_SUFFIX


def _iso(dt: datetime | None) -> str:
    if dt is None:
        return "-"
    return dt.isoformat()


def _tojson(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"))


def _build_env(*, templates_dir: str) -> Environment:
    env = Environment(  # noqa: S701 - Jinja2 intended for templating
        loader=FileSystemLoader(templates_dir),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )

    # Filters (pipe-friendly)
    env.filters["kv"] = _fmt_kv
    env.filters["first"] = _first_non_empty
    env.filters["iso"] = _iso
    env.filters["tojson"] = _tojson
    env.filters["truncate"] = _truncate

    # Globals (function-call style)
    env.globals["kv"] = _fmt_kv
    env.globals["first"] = _first_non_empty
    env.globals["iso"] = _iso
    env.globals["tojson"] = _tojson
    env.globals["truncate"] = _truncate

    # A helper similar to Alertmanager's {{ template "name" . }}:
    # render a named template with the current context.
    def _template(name: str, **kwargs: Any) -> str:
        t = env.get_template(name)
        return t.render(**kwargs)

    env.globals["template"] = _template
    return env


def try_render_message_template(
    *,
    payload: AlertmanagerWebhookV4,
    target: Target,
    template_name: str | None,
    template_inline: str | None,
    max_alerts: int,
    templates_dir: str,
) -> tuple[bool, str]:
    """
    Returns (used_template, text).
    If template is not configured, used_template=False.
    If template is configured but fails to render, used_template=True and raises TemplateError.
    """

    if not template_name and not template_inline:
        return False, ""

    env = _build_env(templates_dir=templates_dir)

    ctx: dict[str, Any] = {
        "payload": payload,
        "alerts": payload.alerts[: max(0, max_alerts)],
        "target": target,
        "max_alerts": max_alerts,
    }

    try:
        if template_inline:
            rendered = env.from_string(template_inline).render(**ctx)
        else:
            rendered = env.get_template(template_name).render(**ctx)  # type: ignore[arg-type]
    except TemplateError:
        raise

    return True, _truncate(rendered.strip())

