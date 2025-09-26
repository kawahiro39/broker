import os
import secrets
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Generator, List, Mapping, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

DEFAULT_DATABASE_URL = (
    "postgresql://postgres:#Hiro22199@34.180.84.255:5432/postgres"
)
DATABASE_URL = os.getenv("DATABASE_URL") or DEFAULT_DATABASE_URL
POOL_MIN_SIZE = int(os.getenv("DB_POOL_MIN_SIZE", "1"))
POOL_MAX_SIZE = int(os.getenv("DB_POOL_MAX_SIZE", "5"))
ALLOWED_ORIGINS = list(
    filter(None, (origin.strip() for origin in os.getenv("ALLOWED_ORIGINS", "").split(",")))
)


if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL environment variable is required to persist auth IDs in PostgreSQL."
    )


connection_pool: Optional[ConnectionPool] = None


def get_connection_pool() -> ConnectionPool:
    global connection_pool
    if connection_pool is None:
        connection_pool = ConnectionPool(
            conninfo=DATABASE_URL,
            min_size=POOL_MIN_SIZE,
            max_size=POOL_MAX_SIZE,
        )
    return connection_pool


@contextmanager
def get_cursor() -> Generator[tuple[Connection, Any], None, None]:
    pool = get_connection_pool()
    with pool.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            try:
                yield conn, cur
            except Exception:
                conn.rollback()
                raise


def init_db() -> None:
    with get_cursor() as (conn, cur):
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS auth_ids (
                id TEXT PRIMARY KEY,
                customer_id TEXT,
                label TEXT,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        conn.commit()


def create_auth_id(customer_id: str, label: Optional[str]) -> str:
    auth_id = secrets.token_urlsafe(32)
    created_at = datetime.now(timezone.utc)
    with get_cursor() as (conn, cur):
        cur.execute(
            """
            INSERT INTO auth_ids (id, customer_id, label, is_active, created_at)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (auth_id, customer_id, label, True, created_at),
        )
        conn.commit()
    return auth_id


def list_auth_ids() -> List[Mapping[str, Any]]:
    with get_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT id, customer_id, label, is_active, created_at
            FROM auth_ids
            ORDER BY created_at DESC
            """
        )
        rows = cur.fetchall()
    return rows


def get_auth_id(auth_id: str) -> Optional[Mapping[str, Any]]:
    with get_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT id, customer_id, label, is_active, created_at
            FROM auth_ids
            WHERE id = %s
            """,
            (auth_id,),
        )
        row = cur.fetchone()
    return row


def set_auth_id_status(auth_id: str, is_active: bool) -> bool:
    with get_cursor() as (conn, cur):
        cur.execute(
            "UPDATE auth_ids SET is_active = %s WHERE id = %s",
            (is_active, auth_id),
        )
        updated = cur.rowcount > 0
        conn.commit()
        return updated


def is_auth_id_valid(auth_id: str) -> bool:
    with get_cursor() as (_, cur):
        cur.execute(
            "SELECT 1 FROM auth_ids WHERE id = %s AND is_active = TRUE",
            (auth_id,),
        )
        return cur.fetchone() is not None


class AuthIdResponse(BaseModel):
    auth_id: str
    customer_id: Optional[str]
    label: Optional[str]
    is_active: bool
    created_at: str


class CreateAuthIdRequest(BaseModel):
    customer_id: str = Field(..., min_length=1)
    label: Optional[str] = None


class VerifyRequest(BaseModel):
    auth_id: str = Field(..., min_length=1)


class VerifyResponse(BaseModel):
    is_valid: bool


def to_utc_isoformat(value: Any) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return str(value)


def row_to_auth_response(row: Mapping[str, Any]) -> AuthIdResponse:
    return AuthIdResponse(
        auth_id=row["id"],
        customer_id=row.get("customer_id"),
        label=row.get("label"),
        is_active=bool(row["is_active"]),
        created_at=to_utc_isoformat(row["created_at"]),
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
    auth_id = create_auth_id(payload.customer_id, payload.label)
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

