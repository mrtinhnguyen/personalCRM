"""Import a collector export when its contents change, independently of WeChat."""

import argparse
import hashlib
import json
import time
from pathlib import Path

from sqlalchemy import text

from .db import SessionLocal
from .full_migration import load_linkedin, materialize_remote_media


def sync(path: Path):
    if not path.is_file():
        return
    digest = hashlib.sha256(json.dumps(json.loads(path.read_text()).get("profiles", []), sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    with SessionLocal() as db:
        # One importer per file, including manual invocations alongside the watcher.
        if not db.execute(text("SELECT pg_try_advisory_lock(11803291)")).scalar_one():
            return
        try:
            previous = db.execute(text("""
                SELECT cursor_value FROM source_cursors
                WHERE source = 'linkedin' AND stream = 'collector_export'
            """)).scalar_one_or_none()
            if previous == digest:
                return
            mapping = {str(row.external_id).removeprefix("contact:"): str(row.profile_id)
                       for row in db.execute(text("""
                SELECT external_id, profile_id FROM identities WHERE provider = 'monica'
                    AND external_id LIKE 'contact:%' AND profile_id IS NOT NULL
            """))}
            load_linkedin(db, path, mapping)
            queued = materialize_remote_media(db, Path("/data/media"))
            db.execute(text("""
                INSERT INTO source_cursors(source, stream, cursor_value, batch_id)
                SELECT 'linkedin', 'collector_export', :digest, id FROM import_batches
                WHERE source = 'linkedin' AND status = 'complete'
                ORDER BY completed_at DESC LIMIT 1
                ON CONFLICT(source, stream) DO UPDATE SET
                    cursor_value = EXCLUDED.cursor_value, updated_at = now()
            """), {"digest": digest})
            db.commit()
            print(json.dumps({"linkedin_export": digest, "media_queued": queued}), flush=True)
        finally:
            db.rollback()
            db.execute(text("SELECT pg_advisory_unlock(11803291)"))
            db.commit()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--watch", action="store_true")
    args = parser.parse_args()
    while True:
        try:
            sync(args.source)
        except Exception as exc:
            if not args.watch:
                raise
            print(json.dumps({"linkedin_sync_error": type(exc).__name__}), flush=True)
        if not args.watch:
            break
        time.sleep(60)


if __name__ == "__main__":
    main()
