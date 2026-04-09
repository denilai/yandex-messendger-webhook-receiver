from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class AlertmanagerAlertV4(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: Literal["firing", "resolved"]
    labels: dict[str, str]
    annotations: dict[str, str]
    startsAt: datetime
    endsAt: datetime
    generatorURL: str | None = None
    fingerprint: str | None = None


class AlertmanagerWebhookV4(BaseModel):
    model_config = ConfigDict(extra="allow")

    version: Literal["4"]
    status: Literal["firing", "resolved"]
    groupKey: str
    receiver: str
    truncatedAlerts: int
    groupLabels: dict[str, str]
    commonLabels: dict[str, str]
    commonAnnotations: dict[str, str]
    externalURL: str | None = None
    alerts: list[AlertmanagerAlertV4]

    # forward-compatible placeholder for unknown fields, while still typing known ones
    def extra_fields(self) -> dict[str, Any]:
        return {
            k: v
            for k, v in self.__pydantic_extra__.items()  # type: ignore[union-attr]
        } if self.__pydantic_extra__ else {}

