from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings

settings = get_settings()
engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def migrate() -> None:
    """Run ordered, idempotent SQL migrations."""
    from pathlib import Path

    candidates = [Path("/migrations")]
    source_path = Path(__file__).resolve()
    if len(source_path.parents) > 3:
        candidates.append(source_path.parents[3] / "migrations")
    migrations_dir = next((path for path in candidates if path.exists()), None)
    if migrations_dir is None:
        raise FileNotFoundError("migrations directory not found")
    with engine.begin() as connection:
        connection.execute(
            text("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
              version TEXT PRIMARY KEY,
              applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
        )
        applied = {
            row[0] for row in connection.execute(text("SELECT version FROM schema_migrations"))
        }
        for migration_path in sorted(migrations_dir.glob("*.sql")):
            if migration_path.name in applied:
                continue
            connection.execute(text(migration_path.read_text(encoding="utf-8")))
            connection.execute(
                text("INSERT INTO schema_migrations(version) VALUES (:version)"),
                {"version": migration_path.name},
            )
