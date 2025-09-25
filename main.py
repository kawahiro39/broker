import os
from typing import Set

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from google.auth import default
from google.auth.transport.requests import AuthorizedSession

app = FastAPI()

ALLOWED_ORIGINS: Set[str] = set(filter(None, (os.getenv("ALLOWED_ORIGINS","").split(","))))
BROKER_API_KEY = os.getenv("BROKER_API_KEY")  # Bubble（サーバー側）だけが知っている秘密値
SA_EMAIL = os.getenv("SA_EMAIL")              # 例: broker-sa@solarnova.iam.gserviceaccount.com
PDF_API_AUD = os.getenv("PDF_API_AUD")        # 例: https://docxexcel2pdf-...run.app

# CORS（必要なOriginだけ許可）
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(ALLOWED_ORIGINS) if ALLOWED_ORIGINS else [],
    allow_credentials=False,
    allow_methods=["POST", "OPTIONS", "GET"],
    allow_headers=["*"],
)

@app.get("/healthz")
def healthz():
    return {"ok": True}

@app.post("/token")
def issue_token(request: Request):
    # 1) ドメイン制限（Origin もしくは Referer を軽くチェック）
    origin = request.headers.get("origin") or request.headers.get("referer","")
    if ALLOWED_ORIGINS:
        if not any(origin.startswith(o) for o in ALLOWED_ORIGINS):
            raise HTTPException(status_code=403, detail="origin not allowed")

    # 2) 共有鍵チェック（ブラウザに露出しないサーバー側で付与）
    api_key = request.headers.get("x-api-key")
    if not BROKER_API_KEY or api_key != BROKER_API_KEY:
        raise HTTPException(status_code=401, detail="invalid api key")

    # 3) IAM Credentials API: generateIdToken で PDF API 向けのIDトークンを発行
    if not (SA_EMAIL and PDF_API_AUD):
        raise HTTPException(status_code=500, detail="missing env (SA_EMAIL or PDF_API_AUD)")

    creds, _ = default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    authed = AuthorizedSession(creds)

    url = f"https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/{SA_EMAIL}:generateIdToken"
    payload = {"audience": PDF_API_AUD, "includeEmail": True}

    r = authed.post(url, json=payload)
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"iamcredentials error: {r.text}")

    id_token = r.json().get("token")
    if not id_token:
        raise HTTPException(status_code=502, detail="id_token empty")

    return JSONResponse({"id_token": id_token})
