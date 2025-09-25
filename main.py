import os
import secrets
import sqlite3
from datetime import datetime
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


DB_PATH = os.getenv("AUTH_DB_PATH", "auth_ids.db")
ALLOWED_ORIGINS = list(
    filter(None, (origin.strip() for origin in os.getenv("ALLOWED_ORIGINS", "").split(",")))
)


def init_db() -> None:
    directory = os.path.dirname(DB_PATH)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS auth_ids (
                id TEXT PRIMARY KEY,
                label TEXT,
                is_active INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )


def create_auth_id(label: Optional[str]) -> str:
    auth_id = secrets.token_urlsafe(32)
    created_at = datetime.utcnow().isoformat() + "Z"
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO auth_ids (id, label, is_active, created_at) VALUES (?, ?, ?, ?)",
            (auth_id, label, 1, created_at),
        )
    return auth_id


def list_auth_ids() -> List[sqlite3.Row]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, label, is_active, created_at FROM auth_ids ORDER BY created_at DESC"
        ).fetchall()
    return rows


def get_auth_id(auth_id: str) -> Optional[sqlite3.Row]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT id, label, is_active, created_at FROM auth_ids WHERE id = ?",
            (auth_id,),
        ).fetchone()
    return row


def set_auth_id_status(auth_id: str, is_active: bool) -> bool:
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            "UPDATE auth_ids SET is_active = ? WHERE id = ?",
            (1 if is_active else 0, auth_id),
        )
        return cur.rowcount > 0


def is_auth_id_valid(auth_id: str) -> bool:
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            "SELECT 1 FROM auth_ids WHERE id = ? AND is_active = 1",
            (auth_id,),
        )
        return cur.fetchone() is not None


class AuthIdResponse(BaseModel):
    auth_id: str
    label: Optional[str]
    is_active: bool
    created_at: str


class CreateAuthIdRequest(BaseModel):
    label: Optional[str] = None


class VerifyRequest(BaseModel):
    auth_id: str = Field(..., min_length=1)


class VerifyResponse(BaseModel):
    is_valid: bool


def row_to_auth_response(row: sqlite3.Row) -> AuthIdResponse:
    return AuthIdResponse(
        auth_id=row["id"],
        label=row["label"],
        is_active=bool(row["is_active"]),
        created_at=row["created_at"],
    )


app = FastAPI()

if ALLOWED_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=False,
    )


@app.on_event("startup")
def startup_event() -> None:
    init_db()


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.post("/auth-ids", response_model=AuthIdResponse)
def issue_auth_id(payload: CreateAuthIdRequest) -> AuthIdResponse:
    auth_id = create_auth_id(payload.label)
    row = get_auth_id(auth_id)
    return row_to_auth_response(row)


@app.get("/auth-ids", response_model=List[AuthIdResponse])
def list_auth_id_endpoint() -> List[AuthIdResponse]:
    rows = list_auth_ids()
    return [row_to_auth_response(row) for row in rows]


@app.get("/auth-ids/{auth_id}", response_model=AuthIdResponse)
def get_auth_id_endpoint(auth_id: str) -> AuthIdResponse:
    row = get_auth_id(auth_id)
    if not row:
        raise HTTPException(status_code=404, detail="auth_id not found")
    return row_to_auth_response(row)


@app.post("/auth-ids/{auth_id}/enable", response_model=AuthIdResponse)
def enable_auth_id(auth_id: str) -> AuthIdResponse:
    updated = set_auth_id_status(auth_id, True)
    if not updated:
        raise HTTPException(status_code=404, detail="auth_id not found")
    row = get_auth_id(auth_id)
    return row_to_auth_response(row)


@app.post("/auth-ids/{auth_id}/disable", response_model=AuthIdResponse)
def disable_auth_id(auth_id: str) -> AuthIdResponse:
    updated = set_auth_id_status(auth_id, False)
    if not updated:
        raise HTTPException(status_code=404, detail="auth_id not found")
    row = get_auth_id(auth_id)
    return row_to_auth_response(row)


@app.post("/auth-ids/verify", response_model=VerifyResponse)
def verify_auth_id(payload: VerifyRequest) -> VerifyResponse:
    is_valid = is_auth_id_valid(payload.auth_id)
    return VerifyResponse(is_valid=is_valid)

