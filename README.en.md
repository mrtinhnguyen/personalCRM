# Monica Next

**Keep your contacts, social updates, and shared memories on your own server.**

A self-hosted personal relationship manager with contact profiles, source-aware history, a social timeline, an interactive relationship graph, and chat archive browsing.

[中文](README.md) · [Deployment](docs/DEPLOYMENT.md) · [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md)

![License: MIT](https://img.shields.io/badge/license-MIT-176653)
![CI](https://github.com/hmumixaM/monica-next/actions/workflows/ci.yml/badge.svg)

![Dashboard with synthetic metrics and numbered contacts](docs/images/dashboard.png)

> These are screenshots of the actual frontend using independently written synthetic fixtures. Contact labels, relationships, messages, organizations, and counts are fictional. No real names, portraits, accounts, locations, private conversations, or deployment addresses are included.

## Features

- **People and groups:** profiles, tags, work and education history, and explicit links between source accounts and people.
- **Source-aware history:** field revisions, original provenance, current projections, and manual edits.
- **Social timeline:** imported WeChat, Instagram, and LinkedIn posts, media, and interactions.
- **Relationship graph:** search, pan, zoom, communities, interaction weights, and optional shared-group connections.
- **Analytics and maps:** monthly activity, interaction rankings, chat summaries, and archived/profile locations. This is not live location tracking.
- **Chat archives:** load conversations on demand and search imported messages.
- **Import pipeline:** signed batches, source cursors, retries, content hashes, resumable uploads, and background processing.
- **Self-hosting:** Docker Compose, PostgreSQL, and local or NAS storage for raw archives and media.

This is an actively evolving personal project. The interface is currently primarily Chinese. It is an independent implementation and is **not the official Monica project or affiliated with Monica or the social platforms**. Import adapters consume archives you already have permission to use; third-party credentials and collection services are not included.

## Screenshots

![Contacts with fictional descriptions and tags](docs/images/contacts.png)

![Synthetic relationship graph](docs/images/relationships.png)

![Timeline containing only fictional updates](docs/images/timeline.png)

## Try the interface

Requires Node.js 22+. No database or third-party account is needed.

```sh
git clone https://github.com/hmumixaM/monica-next.git
cd monica-next
npm ci
npm run demo
```

Open **http://127.0.0.1:4310/dashboard**. The read-only showcase supports the dashboard, contact filtering, timeline, and relationship graph. Profile details, imports, chat, and settings are outside its scope. It never connects to a production database. Stop it with `Ctrl+C`. See [showcase documentation](docs/SHOWCASE.md).

## Run the full application

Requires Docker Engine / Docker Desktop, Docker Compose v2, and Python 3. Node.js is not needed on the host for a Docker deployment.

```sh
git clone https://github.com/hmumixaM/monica-next.git
cd monica-next
python3 scripts/init-env.py
docker compose --env-file .env -f infra/docker-compose.yml up -d --build
python3 scripts/bootstrap.py
```

The initializer generates separate random secrets and refuses to overwrite `.env`. The bootstrap script prompts for the first administrator's email and password without putting the password in shell history. Visit **http://localhost:8080/login**. Database migrations run automatically; bootstrap is disabled once an account exists.

The default installation binds to loopback only. Raw archives and media live in `infra/volumes/data/`; PostgreSQL uses a Docker volume. For real data, configure trusted HTTPS and `APP_ENV=production`, initialize the account before opening access, and use a VPN or controlled reverse proxy. See [deployment, backup, and recovery instructions](docs/DEPLOYMENT.md).

## Architecture

```text
apps/web/             Next.js, React, TypeScript, PWA
services/api/         FastAPI, authentication, imports, queries
services/worker/      Background jobs and metrics
packages/contracts/   Shared TypeScript contracts
importers/            Archive adapters for four sources
migrations/           Ordered PostgreSQL migrations
infra/                Compose, Caddy, and operations scripts
scripts/              Setup, synthetic demo, public-content checks
docs/                 Deployment guide and showcase assets
```

The browser reaches the frontend and API through one origin. Immutable revisions and source observations are separate from current read projections. Content and media use SHA-256 deduplication. See the [import contract](importers/README.md) for batch submission.

## Privacy and limitations

The repository contains code, generic configuration templates, synthetic examples, and demonstration screenshots in an independent Git history. Do not publish personal archives, production logs, databases, tokens, or screenshots of real contacts in issues, pull requests, or CI artifacts.

The application includes Argon2id passwords, HttpOnly sessions, Secure cookies in production, CSRF validation, TOTP, recovery codes, session revocation, and signed imports. It has not undergone an independent security audit. Self-hosting does not eliminate external requests: maps use OpenStreetMap tiles, and media import can contact source-platform CDNs. Map requests may disclose the visitor's IP and viewed region to the tile provider. See [SECURITY.md](SECURITY.md).

## Contributing and license

Read [CONTRIBUTING.md](CONTRIBUTING.md) for development and isolated test setup. CI checks Python tests and lint, TypeScript, the Next.js build, Compose configuration, and container builds. Future work includes more public fixtures, archive compatibility, and an English interface, without a committed delivery date.

Project code is released under the [MIT License](LICENSE). Bundled third-party libraries and geographic data retain their own terms and attribution; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
