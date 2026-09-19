# Contributing

Small, focused pull requests and reproducible bug reports are welcome. The UI is
primarily Chinese; issues and contributions may be in Chinese or English.

## Development

Use Node.js 22+, Python 3.11+, `uv`, Docker, and PostgreSQL 16. Start with the
[deployment guide](docs/DEPLOYMENT.md), or `npm run demo` for frontend inspection
with synthetic data.

```sh
npm ci
npm run lint:web
npm run build:web
npm run privacy:check
cd services/api
uv sync --locked
uv run ruff check app tests ../../importers
```

For the complete API suite, use a disposable PostgreSQL instance. Tests create
and drop isolated databases and may reset tables. **Never point
`TEST_DATABASE_URL` at a production database.**

```sh
docker run --rm -d --name monica-next-tests \
  -p 127.0.0.1:55432:5432 \
  -e POSTGRES_USER=crm -e POSTGRES_PASSWORD=crm-test \
  -e POSTGRES_DB=crm_test postgres:16-alpine

# Run from services/api once PostgreSQL is ready.
TEST_DATABASE_URL='postgresql+psycopg://crm:crm-test@127.0.0.1:55432/crm_test' \
  uv run pytest -q

docker stop monica-next-tests
```

## Before submitting

- Explain the observable problem, resulting behavior, and relevant validation.
- Preserve existing field history, account boundaries, and import idempotency.
- Add focused tests for meaningful behavior changes. Use fictional fixtures.
- Keep secrets, personal contacts, exports, precise locations, and production
  screenshots out of commits, test snapshots, issues, and logs.
- Keep third-party license notices when changing bundled vendor assets.
- Run the appropriate checks above and validate Compose if deployment changes.

The public-content checker catches common accidental file types and deployment
identifiers; it is not a complete secret scanner or a replacement for reviewing
the diff. GitHub Actions runs it alongside the standard build and test jobs.

## Reporting

Use a public issue for ordinary bugs and feature requests. For security problems,
follow [SECURITY.md](SECURITY.md) and do not post an exploit or sensitive data in a
public issue. Participate respectfully, assume good intent, and keep discussion
focused on the work. Contributions are provided under this project's MIT license;
bundled third-party material retains its own terms.
