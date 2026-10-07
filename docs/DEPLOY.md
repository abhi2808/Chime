# Deploying Chime

Two containers from `compose.yaml`:

- **backend**: FastAPI and the live loop, one uvicorn worker. It runs `alembic upgrade head` on every start, so migrations are never a separate step.
- **web**: Caddy serving the built React app and proxying `/api` and `/auth` to the backend. Everything is on **one origin**, which the OAuth cookies depend on. Caddy also handles HTTPS itself: give it a domain and it gets and renews a Let's Encrypt certificate.

Data lives in Docker volumes: `chime-data` for the SQLite file, and `caddy-data` for the certificates. Postgres is an optional profile.

Nothing here has been deployed yet. Everything was built and smoke-tested locally on 2026-10-07: both images build, migrations run up and down on Postgres 17, `/api/health` and the SPA fallback answer through Caddy, and `APP_ENV=production` refuses to start with an open allowlist.

## 1. Try it locally first

The Spotify and WHOOP apps already list `http://127.0.0.1:5173/...` as a redirect URI, so the simplest local trial uses that port. Stop `npm run dev` first, because it uses the same port.

```bash
HTTP_PORT=5173 docker compose up -d --build
# open http://127.0.0.1:5173
docker compose logs -f backend
docker compose down          # keeps the volumes; add -v to wipe them
```

The container starts with an empty database in its own volume, not your `data/chime.db`. To bring your local database along:

```bash
docker compose cp data/chime.db backend:/app/data/chime.db && docker compose restart backend
```

## 2. Production settings

`APP_ENV=production` turns a set of checks into a refusal to start. The process exits and names each gap. The checks:

| Setting | Must be |
|---|---|
| `ALLOWED_SPOTIFY_USER_IDS` | Your Spotify account id, plus anyone else you add. If it is empty, the first person to log in owns the install. |
| `ENCRYPTION_KEY`, `SESSION_SECRET` | Set. Reuse your local values if you are moving your local database over, or the stored tokens cannot be decrypted. |
| `COOKIE_SECURE` | `true` |
| `FRONTEND_ORIGIN` | `https://<your domain>` |
| `SPOTIFY_REDIRECT_URI` | `https://<your domain>/auth/spotify/callback` |
| `WHOOP_REDIRECT_URI` | `https://<your domain>/auth/whoop/callback` |
| `ENABLE_DEV_API` | `false` |

Also set these:

```dotenv
SITE_ADDRESS=chime.example.com   # Caddy fetches a certificate for this name
MUSICBRAINZ_USER_AGENT=Chime/0.1 ( https://github.com/<you>/chime )
```

To find your Spotify account id, open your profile in Spotify, choose Share → Copy link to profile, and take the part after `/user/`.

### Redirect URIs

Add the https URIs on both developer dashboards **next to** the `127.0.0.1` ones, so local development keeps working:

- Spotify (developer.spotify.com → your app → Settings → Redirect URIs): `https://chime.example.com/auth/spotify/callback`
- WHOOP (developer.whoop.com → your app): `https://chime.example.com/auth/whoop/callback`

The Spotify app stays in Development Mode: up to 5 users, each added by hand under User Management. That limit is a second allowlist on Spotify's side, and Chime's own allowlist still applies.

## 3. EC2

This is a personal app with one live session at a time, so it needs very little:

- **Instance:** `t4g.small` (ARM, 2 GB) on Ubuntu 24.04 or Amazon Linux 2023. Every image has an arm64 build, including the psycopg wheel. A `t4g.micro` works for SQLite, but building the frontend image on it is slow.
- **Storage:** the default 8 GB gp3 is plenty. The database is a few MB.
- **Elastic IP**, with a DNS `A` record for your domain pointing at it. Caddy cannot get a certificate until the name resolves to the instance.
- **Security group:** 22 from your own IP only, and 80 and 443 from anywhere. Caddy needs port 80 open for the certificate challenge and the http→https redirect.

```bash
# On the instance (Ubuntu)
sudo apt-get update && sudo apt-get install -y docker.io docker-compose-v2 git
sudo usermod -aG docker $USER && newgrp docker

git clone https://github.com/<you>/chime.git && cd chime
cp .env.example .env && nano .env      # the production settings above
docker compose up -d --build
docker compose logs -f                 # look for "chime backend ready" and Caddy's certificate
```

Then open `https://chime.example.com`, log in with Spotify, connect WHOOP from Settings, and run a library sync from Library.

### Updating

```bash
git pull && docker compose up -d --build
```

Migrations run automatically when the backend starts.

### Backups

SQLite can be copied safely while the app is running, through its own backup API:

```bash
docker compose exec backend python -c "import sqlite3; s=sqlite3.connect('/app/data/chime.db'); d=sqlite3.connect('/app/data/backup.db'); s.backup(d); d.close()"
docker compose cp backend:/app/data/backup.db ./chime-$(date +%F).db
```

Keep `.env` backed up as well. Without `ENCRYPTION_KEY` the stored OAuth tokens cannot be read, and everyone has to log in again.

### Scripts

The maintenance scripts ship in the image:

```bash
docker compose exec backend python -m scripts.tag_spike --limit 5000
docker compose exec backend python -m scripts.evaluate --days 30
```

`data/tag_map.yaml` is baked into the image. After editing it, run `docker compose up -d --build`, then `docker compose exec backend python -m scripts.retag --write`.

## 4. Postgres instead of SQLite (optional)

```dotenv
POSTGRES_PASSWORD=<something long>
DATABASE_URL=postgresql+psycopg://chime:<same password>@postgres:5432/chime
```

```bash
docker compose --profile postgres up -d --build
```

This starts empty. Nothing copies an existing SQLite database across. CI runs every migration up and down against Postgres, so the schema stays compatible.

## 5. Things to know

- **Run exactly one backend.** The live loop (playback poll, adaptation, WHOOP refresh) runs inside the API process. Two replicas, or `--workers 2`, means two pollers fighting over the same session. To run a second process for scripts, give it `ENABLE_SCHEDULER=false`.
- **Idle costs nothing.** With no live session, the loop makes no outbound requests.
- **Logs** never contain tokens or raw WHOOP payloads. `docker compose logs backend` is safe to paste.
- **CI** (`.github/workflows/ci.yml`) runs on every push: backend tests, migrations on SQLite and Postgres, frontend typecheck, lint and build, and both images built (not pushed). Deploying stays a manual `git pull` on the box.
