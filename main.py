"""Entry point for running the TriFiVend MVP API with Uvicorn."""

from __future__ import annotations

from backend.app import create_app

app = create_app()
