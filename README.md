# Managers That Suck — Persistence Package

Flask + Postgres backend, the API-wired SPA, and a one-command Docker stack
with automatic HTTPS. Reviews persist, scores are computed server-side, and
reviewer identity is never stored.

## What's in the box

    app.py              Flask app — API + serves the SPA
    models.py           Companies / Managers / Assessments (write-once)
    scoring.py          Server-side MTS-360 scoring + validation
    seed.py             Demo dataset, loaded on first boot (idempotent)
    static/index.html   The SPA, wired to the API (falls back to demo mode
                        automatically if no backend is reachable)
    Dockerfile          Gunicorn-served Python image
    docker-compose.yml  web + postgres + caddy
    Caddyfile           Your domain → automatic Let's Encrypt HTTPS
    .env.example        The three secrets you must set

## Architecture

    Browser ── HTTPS ──> Caddy ──> Gunicorn/Flask ──> Postgres
                         (certs     (API + static)     (volume-backed)
                          automatic)

API: `GET /api/bootstrap`, `POST /api/managers`,
`POST /api/managers/<id>/assessments` (perspective `team` files a rating;
`self` publishes the improvement plan). The server recomputes every score
from raw answers — client numbers are never trusted. Anti-abuse built in:
one team filing per reviewer hash per manager per 90 days (HTTP 409),
payload validation (exact answer counts, 1–5 ranges), and 24-month decay
stamped on every assessment.

Anonymity: the reviewer hash is `sha256(SALT + ip + user-agent)` — one-way,
never reversed, never joined to anything. No accounts, no emails, no names.

---

## Deploy on a public server (~10 minutes, ~$5/month)

### 1. Get a VPS
Hetzner CX22 or a DigitalOcean basic droplet, Ubuntu 24.04. Note its IP.

### 2. Point your domain
At your DNS host (Cloudflare), create an **A record**: `@` → your server IP.
**Important:** set it to *DNS only* (grey cloud) for the first deploy so
Caddy can obtain its certificate. You can flip the proxy on afterwards
(then set Cloudflare SSL mode to *Full (strict)*).

### 3. Install Docker on the server
    ssh root@YOUR_SERVER_IP
    curl -fsSL https://get.docker.com | sh

### 4. Upload the package
From your machine:
    scp -r mts-deploy root@YOUR_SERVER_IP:/opt/mts
(or push it to a git repo and `git clone` on the server)

### 5. Configure secrets
    cd /opt/mts
    cp .env.example .env
    nano .env        # set DOMAIN, POSTGRES_PASSWORD, SECRET_SALT
Generate strong values with: `openssl rand -hex 24`

### 6. Launch
    docker compose up -d --build

That's it. Within ~60 seconds Caddy obtains certificates and
**https://yourdomain.com** is live, seeded, and persisting.

### Operations
    docker compose logs -f web                  # tail the app
    docker compose up -d --build                # deploy a change
    docker compose exec db pg_dump -U mts mts > backup_$(date +%F).sql   # backup
    cat backup.sql | docker compose exec -T db psql -U mts mts           # restore

---

## Alternative: Render.com (no server administration)

1. Push this folder to a GitHub repo.
2. Render → New → Web Service → connect repo. It detects the Dockerfile.
3. Render → New → PostgreSQL (free tier works to start).
4. On the web service, set env vars: `DATABASE_URL` (from the Postgres
   instance, *Internal URL*) and `SECRET_SALT`.
5. Settings → Custom Domains → add your domain, create the CNAME it shows.

Caddy/compose aren't used on Render — it terminates HTTPS for you.

---

## Local development

    pip install -r requirements.txt
    python app.py            # http://localhost:8000 — SQLite, auto-seeded

## Roadmap notes (already structured for)

- `Assessment` rows are write-once: a nightly job can replace the v1
  blend with a true recency-weighted recompute without API changes.
- `Manager.claimed` exists for the verification flow (work-email domain
  match) before self-assessments can publish.
- Postgres row-level security and a read-only candidate API are the next
  hardening steps when traffic justifies them.
