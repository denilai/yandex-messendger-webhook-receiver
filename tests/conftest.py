from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import settings as settings_module
from app.models.alertmanager import AlertmanagerWebhookV4


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BASIC_AUTH_USERNAME", "user")
    monkeypatch.setenv("BASIC_AUTH_PASSWORD", "pass")
    monkeypatch.setenv("BASIC_AUTH_REALM", "test-realm")
    monkeypatch.setenv("YANDEX_OAUTH_TOKEN", "token")
    monkeypatch.setenv("YANDEX_API_BASE", "https://botapi.messenger.yandex.net")
    monkeypatch.setenv("YANDEX_HTTP_TIMEOUT_SECONDS", "1")
    monkeypatch.setenv("FAIL_ON_YANDEX_4XX", "false")
    settings_module.get_settings.cache_clear()


@pytest.fixture()
def alertmanager_payload() -> AlertmanagerWebhookV4:
    p = Path(__file__).parent / "fixtures" / "alertmanager_v4_valid.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    return AlertmanagerWebhookV4.model_validate(data)

