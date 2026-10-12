"""Minimal FastAPI backend for the silk-sidecar hello example."""

from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="silk-sidecar hello", root_path=os.environ.get("API_ROOT_PATH", ""))

origins = [
    o.strip()
    for o in os.environ.get("CORS_ORIGINS", "http://127.0.0.1:3000,http://localhost:3000").split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "service": "hello-api"}


@app.get("/api/hello")
def hello(name: str = "Silk") -> dict:
    return {
        "message": f"Hello, {name}!",
        "utc": datetime.now(timezone.utc).isoformat(),
    }
