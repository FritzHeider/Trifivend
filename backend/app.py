"""FastAPI application factory for the TriFiVend MVP."""

from __future__ import annotations

from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware

from .config import ensure_data_directory, get_settings
from .schemas import CallCreate, CallList, CallRead, CallStatusUpdate
from .store import CallRecord, CallStore
from .twilio_client import TwilioConfig, TwilioService


def create_app() -> FastAPI:
    settings = get_settings()
    ensure_data_directory(settings.data_path)

    store = CallStore(settings.data_path)
    twilio_config = (
        TwilioConfig(
            account_sid=settings.twilio_account_sid or "",
            auth_token=settings.twilio_auth_token or "",
            from_number=settings.twilio_from_number or "",
        )
        if settings.twilio_enabled
        else None
    )
    twilio_service = TwilioService(twilio_config)

    app = FastAPI(title="TriFiVend API", version="0.1.0", docs_url="/docs")
    app.state.store = store
    app.state.twilio = twilio_service
    app.state.settings = settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health", summary="Simple health check")
    async def health() -> dict[str, object]:
        return {
            "status": "ok",
            "twilio": app.state.twilio.enabled,
            "environment": app.state.settings.environment,
        }

    def get_store(request: Request) -> CallStore:
        return request.app.state.store

    def get_twilio(request: Request) -> TwilioService:
        return request.app.state.twilio

    @app.get("/calls", response_model=CallList, summary="List recent calls")
    async def list_calls(store: CallStore = Depends(get_store)) -> CallList:
        calls = [CallRead.model_validate(call) for call in store.list_calls()]
        return CallList(calls=calls)

    @app.post(
        "/calls",
        response_model=CallRead,
        status_code=status.HTTP_201_CREATED,
        summary="Create a new outbound call",
    )
    async def create_call(
        payload: CallCreate,
        store: CallStore = Depends(get_store),
        twilio: TwilioService = Depends(get_twilio),
    ) -> CallRead:
        call_id = str(uuid4())
        record = CallRecord(
            id=call_id,
            to_number=payload.to_number,
            message=payload.message,
        )
        store.add_call(record)

        if twilio.enabled:
            try:
                provider_sid = twilio.place_call(to_number=payload.to_number, message=payload.message)
            except RuntimeError as exc:
                store.update_status(call_id, status="error")
                raise HTTPException(status_code=500, detail=f"Failed to place call: {exc}")
            else:
                store.update_status(call_id, status="queued", provider_sid=provider_sid)
        else:
            store.update_status(call_id, status="recorded")

        return CallRead.model_validate(store.get(call_id))

    @app.post(
        "/calls/{call_id}/status",
        response_model=CallRead,
        summary="Update the status of an existing call",
    )
    async def update_status(
        call_id: str,
        payload: CallStatusUpdate,
        store: CallStore = Depends(get_store),
    ) -> CallRead:
        try:
            record = store.update_status(
                call_id,
                status=payload.status,
                provider_sid=payload.provider_sid,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return CallRead.model_validate(record)

    return app
