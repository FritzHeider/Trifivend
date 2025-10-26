"""Persistent storage helpers for call records."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class CallRecord(BaseModel):
    """Represents a single outbound call attempt."""

    id: str
    to_number: str
    message: str
    status: str = Field(default="pending")
    provider_sid: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc)


class CallStore:
    """Tiny JSON-backed call store suitable for an MVP."""

    def __init__(self, path: Path):
        self._path = path
        self._lock = Lock()
        self._calls: Dict[str, CallRecord] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text("utf-8"))
        except json.JSONDecodeError:
            data = []
        for item in data:
            record = CallRecord.model_validate(item)
            self._calls[record.id] = record

    def _save(self) -> None:
        payload = [record.model_dump(mode="json") for record in self._calls.values()]
        self._path.write_text(json.dumps(payload, indent=2), "utf-8")

    def list_calls(self) -> List[CallRecord]:
        with self._lock:
            return sorted(self._calls.values(), key=lambda c: c.created_at, reverse=True)

    def add_call(self, record: CallRecord) -> CallRecord:
        with self._lock:
            self._calls[record.id] = record
            self._save()
            return record

    def update_status(
        self,
        call_id: str,
        *,
        status: str,
        provider_sid: Optional[str] = None,
    ) -> CallRecord:
        with self._lock:
            if call_id not in self._calls:
                raise KeyError(f"Call {call_id} not found")
            record = self._calls[call_id]
            record.status = status
            if provider_sid is not None:
                record.provider_sid = provider_sid
            record.touch()
            self._save()
            return record

    def get(self, call_id: str) -> CallRecord:
        with self._lock:
            if call_id not in self._calls:
                raise KeyError(f"Call {call_id} not found")
            return self._calls[call_id]
