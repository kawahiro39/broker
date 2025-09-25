# Broker API Guide

このサービスは FastAPI で実装された認証 ID 管理 API です。Bubble などのノーコードアプリから認証 ID を取得し、Cloud Run 上の保護対象 API にリクエストする際のヘッダー認証に利用できます。

## セットアップ

1. 依存関係をインストールします。
   ```bash
   pip install -r requirements.txt
   ```
2. 必要に応じて環境変数を設定します。

   | 変数名 | 説明 | 既定値 |
   | ------ | ---- | ------ |
   | `AUTH_DB_PATH` | 認証 ID を保持する SQLite ファイルのパス。存在しないディレクトリは自動作成されます。 | `auth_ids.db` |
   | `ALLOWED_ORIGINS` | CORS を許可するオリジン。カンマ区切りで指定します。Bubble のアプリドメインなどを設定してください。 | （未設定） |

3. API サーバーを起動します。
   ```bash
   uvicorn main:app --host 0.0.0.0 --port 8080
   ```

## CORS 設定について

`ALLOWED_ORIGINS` を指定すると該当オリジンからのブラウザアクセスが許可されます。プリフライトリクエストにも対応しているため、Bubble から `POST` で JSON ボディを送るケースでも利用できます。

## エンドポイント一覧

| メソッド / パス | 説明 | リクエスト例 | 成功時レスポンス |
| ---------------- | ---- | ------------ | ---------------- |
| `GET /healthz` | ヘルスチェック | なし | `{ "ok": true }` |
| `POST /auth-ids` | 認証 ID の新規発行 | `{"label": "bubble-client"}` | `{"auth_id": "...", "label": "bubble-client", "is_active": true, "created_at": "..."}` |
| `GET /auth-ids` | 認証 ID の一覧取得 | なし | `[{...}, ...]` |
| `GET /auth-ids/{auth_id}` | 認証 ID の単体取得 | なし | `{...}` |
| `POST /auth-ids/{auth_id}/enable` | 認証 ID を有効化 | なし | `{...}` |
| `POST /auth-ids/{auth_id}/disable` | 認証 ID を無効化 | なし | `{...}` |
| `POST /auth-ids/verify` | 認証 ID の有効性確認 | `{"auth_id": "..."}` | `{ "is_valid": true/false }` |

## Bubble 連携例

1. Bubble から認証 ID 管理画面を作成し、`POST /auth-ids` を呼び出して ID を取得します。
2. 取得した `auth_id` を Cloud Run アプリにリクエストする際のカスタムヘッダー（例: `X-Broker-Auth-ID`）に設定します。
3. Cloud Run 側では受け取ったヘッダーを `POST /auth-ids/verify` に渡し、`is_valid` が `true` の場合にのみ処理を継続します。
4. 利用停止が必要になった場合は Bubble から `POST /auth-ids/{auth_id}/disable`、再開する場合は `POST /auth-ids/{auth_id}/enable` を呼び出します。

## 簡易動作確認

```bash
python -m compileall main.py
```

## 備考

- 認証 ID には有効期限はありません。無効化 API を利用して手動で制御してください。
- SQLite を利用しているため、単一インスタンスでの運用を想定しています。複数インスタンスで利用する場合は Cloud SQL などの共有データベースへ移行してください。
