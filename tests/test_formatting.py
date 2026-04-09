from __future__ import annotations

from app.models.alertmanager import AlertmanagerWebhookV4
from app.services.formatters import MAX_TEXT_LEN, render_alertmanager_text


def test_formatting_is_deterministic(alertmanager_payload: AlertmanagerWebhookV4) -> None:
    a = render_alertmanager_text(alertmanager_payload)
    b = render_alertmanager_text(alertmanager_payload)
    assert a == b


def test_formatting_truncates_to_6000_chars() -> None:
    many = {
        "version": "4",
        "status": "firing",
        "groupKey": "g",
        "receiver": "r",
        "truncatedAlerts": 0,
        "groupLabels": {"alertname": "X"},
        "commonLabels": {"alertname": "X"},
        "commonAnnotations": {"summary": "s" * 4000, "description": "d" * 4000},
        "externalURL": None,
        "alerts": [
            {
                "status": "firing",
                "labels": {"instance": f"i{n}", "job": "j", "severity": "critical"},
                "annotations": {"summary": "a" * 500, "description": "b" * 500},
                "startsAt": "2026-04-09T12:00:00Z",
                "endsAt": "0001-01-01T00:00:00Z",
                "generatorURL": None,
                "fingerprint": None
            }
            for n in range(50)
        ],
    }
    payload = AlertmanagerWebhookV4.model_validate(many)
    text = render_alertmanager_text(payload)
    assert len(text) <= MAX_TEXT_LEN
    assert "truncated to 6000 chars" in text

