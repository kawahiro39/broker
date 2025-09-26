import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Generator, List, Mapping, Optional, Protocol

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

DATABASE_URL = os.getenv("DATABASE_URL")
POOL_MIN_SIZE = int(os.getenv("DB_POOL_MIN_SIZE", "1"))
POOL_MAX_SIZE = int(os.getenv("DB_POOL_MAX_SIZE", "5"))
AUTH_DB_PATH = os.getenv("AUTH_DB_PATH", "auth_ids.db")
ALLOWED_ORIGINS = list(
    filter(None, (origin.strip() for origin in os.getenv("ALLOWED_ORIGINS", "").split(",")))
)


class AuthRepository(Protocol):
    def init_db(self) -> None:
        ...

    def issue_auth_id(self, customer_id: str, label: Optional[str]) -> Mapping[str, Any]:
        ...

    def list_auth_ids(self) -> List[Mapping[str, Any]]:
        ...

    def get_auth_id(self, auth_id: str) -> Optional[Mapping[str, Any]]:
        ...

    def update_auth_id_status(
        self, auth_id: str, is_active: bool
    ) -> Optional[Mapping[str, Any]]:
        ...

    def is_auth_id_valid(self, auth_id: str) -> bool:
        ...

    def close(self) -> None:
        ...


class PostgresRepository:
    def __init__(self, conninfo: str, min_size: int, max_size: int) -> None:
        self._conninfo = conninfo
        self._min_size = min_size
        self._max_size = max_size
        self._pool: Optional[ConnectionPool] = None

    def _get_pool(self) -> ConnectionPool:
        if self._pool is None:
            self._pool = ConnectionPool(
                conninfo=self._conninfo,
                min_size=self._min_size,
                max_size=self._max_size,
            )
        return self._pool

    @contextmanager
    def _get_cursor(self) -> Generator[tuple[Any, Any], None, None]:
        pool = self._get_pool()
        with pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                yield conn, cur

    def init_db(self) -> None:
        with self._get_cursor() as (conn, cur):
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

    def issue_auth_id(self, customer_id: str, label: Optional[str]) -> Mapping[str, Any]:
        auth_id = secrets.token_urlsafe(32)
        created_at = datetime.now(timezone.utc)
        with self._get_cursor() as (conn, cur):
            cur.execute(
                """
                INSERT INTO auth_ids (id, customer_id, label, is_active, created_at)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, customer_id, label, is_active, created_at
                """,
                (auth_id, customer_id, label, True, created_at),
            )
            row = cur.fetchone()
            conn.commit()
        return row

    def list_auth_ids(self) -> List[Mapping[str, Any]]:
        with self._get_cursor() as (_, cur):
            cur.execute(
                """
                SELECT id, customer_id, label, is_active, created_at
                FROM auth_ids
                ORDER BY created_at DESC
                """
            )
            rows = cur.fetchall()
        return rows

    def get_auth_id(self, auth_id: str) -> Optional[Mapping[str, Any]]:
        with self._get_cursor() as (_, cur):
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

    def update_auth_id_status(
        self, auth_id: str, is_active: bool
    ) -> Optional[Mapping[str, Any]]:
        with self._get_cursor() as (conn, cur):
            cur.execute(
                """
                UPDATE auth_ids
                SET is_active = %s
                WHERE id = %s
                RETURNING id, customer_id, label, is_active, created_at
                """,
                (is_active, auth_id),
            )
            row = cur.fetchone()
            conn.commit()
        return row

    def is_auth_id_valid(self, auth_id: str) -> bool:
        with self._get_cursor() as (_, cur):
            cur.execute(
                "SELECT 1 FROM auth_ids WHERE id = %s AND is_active = TRUE",
                (auth_id,),
            )
            return cur.fetchone() is not None

    def close(self) -> None:
        if self._pool is not None:
            self._pool.close()
            self._pool = None


class SQLiteRepository:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS auth_ids (
                    id TEXT PRIMARY KEY,
                    customer_id TEXT,
                    label TEXT,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def issue_auth_id(self, customer_id: str, label: Optional[str]) -> Mapping[str, Any]:
        auth_id = secrets.token_urlsafe(32)
        created_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO auth_ids (id, customer_id, label, is_active, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (auth_id, customer_id, label, 1, created_at),
            )
            cursor = conn.execute(
                """
                SELECT id, customer_id, label, is_active, created_at
                FROM auth_ids
                WHERE id = ?
                """,
                (auth_id,),
            )
            row = cursor.fetchone()
            conn.commit()
        return dict(row) if row else {}

    def list_auth_ids(self) -> List[Mapping[str, Any]]:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT id, customer_id, label, is_active, created_at
                FROM auth_ids
                ORDER BY created_at DESC
                """
            )
            rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def get_auth_id(self, auth_id: str) -> Optional[Mapping[str, Any]]:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT id, customer_id, label, is_active, created_at
                FROM auth_ids
                WHERE id = ?
                """,
                (auth_id,),
            )
            row = cursor.fetchone()
        return dict(row) if row else None

    def update_auth_id_status(
        self, auth_id: str, is_active: bool
    ) -> Optional[Mapping[str, Any]]:
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE auth_ids SET is_active = ? WHERE id = ?",
                (1 if is_active else 0, auth_id),
            )
            if cursor.rowcount == 0:
                conn.commit()
                return None
            row_cursor = conn.execute(
                """
                SELECT id, customer_id, label, is_active, created_at
                FROM auth_ids
                WHERE id = ?
                """,
                (auth_id,),
            )
            row = row_cursor.fetchone()
            conn.commit()
        return dict(row) if row else None

    def is_auth_id_valid(self, auth_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT 1 FROM auth_ids WHERE id = ? AND is_active = 1",
                (auth_id,),
            )
            return cursor.fetchone() is not None

    def close(self) -> None:
        return None


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


if DATABASE_URL:
    repository: AuthRepository = PostgresRepository(
        DATABASE_URL, POOL_MIN_SIZE, POOL_MAX_SIZE
    )
else:
    repository = SQLiteRepository(AUTH_DB_PATH)


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
    repository.init_db()


@app.on_event("shutdown")
def shutdown_event() -> None:
    repository.close()


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.post("/auth-ids", response_model=AuthIdResponse)
def issue_auth_id(payload: CreateAuthIdRequest) -> AuthIdResponse:
    row = repository.issue_auth_id(payload.customer_id, payload.label)
    return row_to_auth_response(row)


@app.get("/auth-ids", response_model=List[AuthIdResponse])
def list_auth_id_endpoint() -> List[AuthIdResponse]:
    rows = repository.list_auth_ids()
    return [row_to_auth_response(row) for row in rows]


@app.get("/auth-ids/{auth_id}", response_model=AuthIdResponse)
def get_auth_id_endpoint(auth_id: str) -> AuthIdResponse:
    row = repository.get_auth_id(auth_id)
    if not row:
        raise HTTPException(status_code=404, detail="auth_id not found")
    return row_to_auth_response(row)


@app.post("/auth-ids/{auth_id}/enable", response_model=AuthIdResponse)
def enable_auth_id(auth_id: str) -> AuthIdResponse:
    row = repository.update_auth_id_status(auth_id, True)
    if not row:
        raise HTTPException(status_code=404, detail="auth_id not found")
    return row_to_auth_response(row)


@app.post("/auth-ids/{auth_id}/disable", response_model=AuthIdResponse)
def disable_auth_id(auth_id: str) -> AuthIdResponse:
    row = repository.update_auth_id_status(auth_id, False)
    if not row:
        raise HTTPException(status_code=404, detail="auth_id not found")
    return row_to_auth_response(row)


@app.post("/auth-ids/verify", response_model=VerifyResponse)
def verify_auth_id(payload: VerifyRequest) -> VerifyResponse:
    is_valid = repository.is_auth_id_valid(payload.auth_id)
    return VerifyResponse(is_valid=is_valid)

