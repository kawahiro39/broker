# Broker API Guide

このサービスは FastAPI で実装された認証 ID 管理 API です。Bubble などのノーコードアプリから認証 ID を取得し、Cloud Run 上の保護対象 API にリクエストする際のヘッダー認証に利用できます。発行された ID には対応する顧客 ID と有効 / 無効の状態が保存されます。

## セットアップ

1. 依存関係をインストールします。
   ```bash
   pip install -r requirements.txt
   ```
2. 必要に応じて環境変数を設定します。

   | 変数名 | 説明 | 既定値 |
   | ------ | ---- | ------ |
| `DATABASE_URL` | Cloud SQL などの PostgreSQL への接続文字列。例: `postgresql://postgres:<password>@<host>:5432/<database>` | （未設定） |
   | `DB_POOL_MIN_SIZE` | PostgreSQL 利用時の接続プール初期コネクション数。 | `1` |
   | `DB_POOL_MAX_SIZE` | PostgreSQL 利用時の接続プール最大コネクション数。 | `5` |
   | `AUTH_DB_PATH` | PostgreSQL を指定しない場合に利用する SQLite ファイルのパス。 | `auth_ids.db` |
   | `ALLOWED_ORIGINS` | CORS を許可するオリジン。カンマ区切りで指定します。Bubble のアプリドメインなどを設定してください。 | （未設定） |

3. API サーバーを起動します。
   ```bash
   uvicorn main:app --host 0.0.0.0 --port 8080
   ```

### Cloud SQL (PostgreSQL) との接続例

Cloud SQL のインスタンスに接続する場合は、Cloud SQL Auth Proxy または Cloud Run の Cloud SQL コネクタを利用してネットワークを確立した上で、
`DATABASE_URL` を以下の形式で設定します。

```bash
export DATABASE_URL="postgresql://<user>:<password>@<proxy_host>:5432/<database>"
```

パブリック IP を利用する場合は、接続先の IP アドレスと作成したユーザー／データベース名を用いて接続文字列を組み立てます。Cloud Run から直接アクセスする場合は、Cloud SQL Auth Proxy のデプロイや Cloud SQL コネクタの設定など、ネットワーク経路の確立が必要です。

## CORS 設定について

`ALLOWED_ORIGINS` を指定すると該当オリジンからのブラウザアクセスが許可されます。プリフライトリクエストにも対応しているため、Bubble から `POST` で JSON ボディを送るケースでも利用できます。

## エンドポイント一覧

| メソッド / パス | 説明 | リクエスト例 | 成功時レスポンス |
| ---------------- | ---- | ------------ | ---------------- |
| `GET /healthz` | ヘルスチェック | なし | `{ "ok": true }` |
| `POST /auth-ids` | 認証 ID の新規発行 | `{"customer_id": "customer-123", "label": "bubble-client"}` | `{"auth_id": "...", "customer_id": "customer-123", "label": "bubble-client", "is_active": true, "created_at": "..."}` |
| `GET /auth-ids` | 認証 ID の一覧取得 | なし | `[{...}, ...]` |
| `GET /auth-ids/{auth_id}` | 認証 ID の単体取得 | なし | `{...}` |
| `POST /auth-ids/{auth_id}/enable` | 認証 ID を有効化 | なし | `{...}` |
| `POST /auth-ids/{auth_id}/disable` | 認証 ID を無効化 | なし | `{...}` |
| `POST /auth-ids/verify` | 認証 ID の有効性確認 | `{"auth_id": "..."}` | `{ "is_valid": true/false }` |

## Bubble 連携例

1. Bubble から認証 ID 管理画面を作成し、`POST /auth-ids` を呼び出して ID を取得します。
2. 取得した `auth_id` と紐づく `customer_id` を Cloud Run アプリにリクエストする際のカスタムヘッダー（例: `X-Broker-Auth-ID`）に設定します。
3. Cloud Run 側では受け取ったヘッダーを `POST /auth-ids/verify` に渡し、`is_valid` が `true` の場合にのみ処理を継続します。
4. 利用停止が必要になった場合は Bubble から `POST /auth-ids/{auth_id}/disable`、再開する場合は `POST /auth-ids/{auth_id}/enable` を呼び出します。

## 簡易動作確認

```bash
python -m compileall main.py
```

## 備考

- 認証 ID には有効期限はありません。無効化 API を利用して手動で制御してください。
- `DATABASE_URL` を設定すると認証 ID は PostgreSQL に保存され、Cloud Run の再起動やスケールアウトを行ってもレコードは保持されます。環境変数を設定しない場合はローカルの SQLite ファイルに保存されるため、Cloud Run の再デプロイ時などに消失します。
