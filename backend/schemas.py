"""Pydantic schemas used by the API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class CallCreate(BaseModel):
    to_number: str = Field(..., min_length=3, description="Destination phone number in E.164 format.")
    message: str = Field(..., min_length=1, max_length=500, description="Message to read during the call.")


class CallRead(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    to_number: str
    message: str
    status: str
    provider_sid: str | None = None
    created_at: datetime
    updated_at: datetime


class CallList(BaseModel):
    calls: list[CallRead]


class CallStatusUpdate(BaseModel):
    status: str = Field(..., min_length=2, description="New status label for the call.")
    provider_sid: str | None = Field(
        default=None,
        description="Optional provider SID if the status update comes from Twilio.",
    )
