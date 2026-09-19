# Deployment and local development

## Local Compose installation

Run all commands from the repository root. `python3 scripts/init-env.py` creates a
private `.env` with independent random secrets. Then start:

```sh
docker compose --env-file .env -f infra/docker-compose.yml up -d --build
python3 scripts/bootstrap.py
```

Open `http://localhost:8080/login`. The default ports bind to `127.0.0.1`; this is
intentional because the first-account bootstrap endpoint is initially available.
The API and PostgreSQL have no separately published ports. Startup waits for
PostgreSQL and migrations; initial image builds can take several minutes.

Compose resolves relative bind mounts from `infra/`. With the default `.env`, raw
archives, media, staging, and exports are under `infra/volumes/data/`.
`infra/init-data.sh` is optional; if used from the repository root, run
`DATA_ROOT=./infra/volumes/data ./infra/init-data.sh` so it uses the same location.

The archive watchers can run without imported data. Existing archive formats are
specific to their source exporters; inspect the adapter and use synthetic input
before importing personal records. No collector credentials are provided.

## NAS and HTTPS

Use `infra/.env.example` as a configuration reference, keeping the actual `.env`
outside version control. Preserve the generated secrets and set:

- `APP_ENV=production` to enable Secure session cookies.
- `DATA_ROOT` to an absolute directory owned by the deployment operator.
- `CRM_SCHEME=https` and `CRM_HOST` to the hostname you control.
- `BIND_ADDRESS` to a specific trusted interface only when remote access is ready.
- `HTTP_PORT` and `HTTPS_PORT` to unused host ports.

The standard Caddyfile uses Caddy's internal CA for private deployments. Install
that CA on trusted clients, or terminate trusted TLS in your existing reverse
proxy. Do not ignore certificate errors. For a public DNS hostname with automatic
ACME certificates, adapt Caddy's TLS settings and networking to your environment.

`infra/Caddyfile.tailscale` supports a certificate/key mounted read-only under
`CERT_ROOT` as `nas.crt` and `nas.key`. Set `CADDYFILE=Caddyfile.tailscale`,
`CRM_TAILSCALE_HOST` to your own hostname, and `CERT_ROOT` to your private
certificate directory. The example hostname is a placeholder.

Complete bootstrap on the host before changing network access. For remote
administration use a VPN such as Tailscale or a controlled reverse proxy. This
single-user application has not been hardened or audited for unrestricted public
hosting. A public source repository does not require a public CRM instance.

## Backups and recovery

Preserve both the database and content files. From the repository root:

```sh
DATA_ROOT=./infra/volumes/data ./infra/backup.sh
```

For an absolute data directory, supply that path instead. The script saves a
PostgreSQL custom-format dump and an archive of `raw`, `staging`, and `exports`.
**It does not back up `media/sha256/`**: snapshot or copy the entire media directory
separately. Keep `.env`, TLS certificates, and any platform stores in secure
backups. Never commit them or attach them to CI artifacts.

Recovery should be rehearsed in a separate Compose project: stop writers, restore
the matching database dump with `pg_restore`, restore media and raw files to their
configured mounts, and only then restart the API and workers. The optional
platform-store migration creates additional databases; back those up as well if
you use it. Do not run destructive restore commands against the only copy of data.

## Development without the application containers

Use Node.js 22+, Python 3.11+, `uv`, and a separate PostgreSQL 16 database.
The root `.env` is for Compose interpolation; it is not automatically the API's
settings file when running from `services/api`. Export development settings in
the shell that starts the API:

```sh
export DATABASE_URL='postgresql+psycopg://crm:YOUR_PASSWORD@127.0.0.1:5432/crm'
export APP_ENV=development
export RAW_ROOT=./runtime/raw
export MEDIA_ROOT=./runtime/media
cd services/api
uv sync --locked
uv run python -m app migrate
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

In another terminal at the repository root:

```sh
npm ci
API_INTERNAL_URL=http://127.0.0.1:8000 npm run dev:web -- --hostname 127.0.0.1
```

Use `python3 scripts/bootstrap.py --url http://127.0.0.1:3000` for a fresh local
database. Direct API documentation is available at `http://127.0.0.1:8000/docs`;
the default Caddyfile forwards `/api/*` and `/health`, not `/docs`.

## CI images

CI builds API, worker, and web containers and retains image archives for seven
days. It does not deploy them. `.dockerignore` excludes `.env`, local data,
runtime files, logs, and keys from the build context. Review that boundary before
adding new archive locations. Deployment scripts under `infra/` are optional
operator tools; configure their destinations for your own server.
