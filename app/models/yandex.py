from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class YandexSendTextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    login: str | None = None
    chat_id: str | None = Field(default=None, alias="chat_id")
    payload_id: str | None = None
    reply_message_id: int | None = None
    disable_notification: bool | None = None
    important: bool | None = None
    disable_web_page_preview: bool | None = None
    thread_id: int | None = None
    inline_keyboard: list[dict] | None = None
    suggest_buttons: dict | None = None

    @model_validator(mode="after")
    def _exactly_one_target(self) -> "YandexSendTextRequest":
        has_login = bool(self.login)
        has_chat = bool(self.chat_id)
        if has_login == has_chat:
            raise ValueError("Exactly one of login or chat_id must be provided")
        return self


class YandexSendTextResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    ok: bool
    message_id: int | None = None
