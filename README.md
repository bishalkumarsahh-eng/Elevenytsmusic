# Juno X Music — Standalone Powerful API v3

Separate API server for multiple Telegram/music bots. Each bot can have its own API key.

## Environment variables
```env
API_NAME=Juno X Music API
ADMIN_KEY=YOUR_LONG_RANDOM_ADMIN_SECRET
API_DB=/tmp/juno_api.sqlite3
MAX_DURATION=900
MAX_RESULTS=20
DOWNLOAD_TIMEOUT=300
```
`API_KEY` is optional legacy compatibility. New installations should use `ADMIN_KEY` and create individual bot keys.

## Generate a bot API key
Open `/docs`, find **POST /admin/keys/create**, click **Try it out**, enter a label such as `Juno Music Bot`, then click **Execute**.

Authorize the admin request with either `X-Admin-Key: YOUR_ADMIN_KEY` or `Authorization: Bearer YOUR_ADMIN_KEY`.

The response contains a `jx_live_...` key. Save it immediately; the raw key is not stored and cannot be displayed again.

## Manage keys
- `POST /admin/keys/create?label=Juno%20Music%20Bot` — create a key
- `GET /admin/keys` — list keys (metadata only)
- `POST /admin/keys/revoke?key_id=1` — revoke by ID
- `POST /admin/keys/revoke?api_key=jx_live_...` — revoke by key

## Music endpoints
- `GET /health`
- `GET /search?q=...&limit=5`
- `GET /info?url=...`
- `GET /download?url=...&type=audio|video`
- `/docs`

## Connect a bot
```env
MUSIC_API_URL=https://YOUR-API-APP.herokuapp.com
MUSIC_API_KEY=jx_live_YOUR_BOT_KEY
```

Use only media you are authorized to access and comply with applicable platform terms and copyright law.
