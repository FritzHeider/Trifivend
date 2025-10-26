"""Thin wrapper around the Twilio REST client."""

from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Optional

from twilio.base.exceptions import TwilioException
from twilio.rest import Client


@dataclass
class TwilioConfig:
    account_sid: str
    auth_token: str
    from_number: str


class TwilioService:
    """Minimal Twilio helper that only exposes what's needed for the MVP."""

    def __init__(self, config: Optional[TwilioConfig]):
        self._config = config
        self._client: Client | None = None
        if config:
            self._client = Client(config.account_sid, config.auth_token)

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def place_call(self, *, to_number: str, message: str) -> str:
        if not self._client or not self._config:
            raise RuntimeError("Twilio is not configured")

        twiml = f"<Response><Say voice='alice'>{html.escape(message)}</Say></Response>"
        try:
            call = self._client.calls.create(
                to=to_number,
                from_=self._config.from_number,
                twiml=twiml,
            )
        except TwilioException as exc:  # pragma: no cover - network error paths are hard to simulate
            raise RuntimeError(str(exc)) from exc
        return str(call.sid)
