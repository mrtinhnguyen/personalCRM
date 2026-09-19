"""Small PostgreSQL-backed worker used for imports and aggregate refreshes."""

import os
import socket
import time
from datetime import datetime, timezone

from sqlalchemy import create_engine, text

from app.remote_media import download_image, enqueue_due_media, materialize_image, media_state, needs_download


DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql+psycopg://crm:crm@localhost:5432/crm")
WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"
engine = create_engine(DATABASE_URL, pool_pre_ping=True)


def claim_job():
    with engine.begin() as db:
        row = db.execute(text("""
          WITH candidate AS (
            SELECT id FROM jobs
            WHERE (status = 'queued' OR (status = 'running' AND locked_at < now() - interval '15 minutes'))
              AND available_at <= now()
            ORDER BY CASE WHEN job_type='media.download' AND payload->>'role' IN ('linkedin_avatar','instagram_avatar')
                          THEN 0 ELSE 1 END, available_at, id
            FOR UPDATE SKIP LOCKED LIMIT 1
          )
          UPDATE jobs SET status = 'running', locked_at = now(), locked_by = :worker, attempts = attempts + 1
          WHERE id = (SELECT id FROM candidate)
          RETURNING id, job_type, payload, attempts
        """), {"worker": WORKER_ID}).mappings().one_or_none()
        return dict(row) if row else None


def finish_job(job_id, error: str | None = None, terminal=False):
    with engine.begin() as db:
        if error:
            db.execute(text("""
              UPDATE jobs SET status = CASE WHEN :terminal OR attempts >= 5 THEN 'failed' ELSE 'queued' END,
                error = :error, available_at = now() + interval '1 minute', locked_at = NULL,
                locked_by = NULL WHERE id = :id
            """), {"id": job_id, "error": error,'terminal':terminal})
        else:
            db.execute(text("""
              UPDATE jobs SET status = 'complete', completed_at = now(), locked_at = NULL,
                locked_by = NULL WHERE id = :id
            """), {"id": job_id})


def execute_job(job):
    downloaded = None
    if job["job_type"] == "media.download":
        with engine.connect() as lookup:
            download_required=needs_download(lookup,job['payload'])
            media_state(lookup,job['payload'],'downloading');lookup.commit()
        if download_required:
            downloaded = download_image(job['payload']['url'], os.environ.get('MEDIA_ROOT','/data/media'))
    with engine.begin() as db:
        if job["job_type"] == "media.download":
            materialize_image(db, job["payload"], os.environ.get("MEDIA_ROOT", "/data/media"), downloaded)
        elif job["job_type"] == "metrics.refresh":
            payload = job["payload"] or {}
            watermark = payload.get("batch_id")
            # Global counts are sampled at most once per ten minutes. Each job
            # still refreshes only the profiles touched by its source batch.
            refresh_global = not db.execute(text("SELECT 1 FROM global_metric_snapshots WHERE computed_at>now()-interval '10 minutes' LIMIT 1")).scalar_one_or_none()
            metrics = {
                "global.profile_count": db.execute(
                    text("SELECT count(*) FROM profiles WHERE archived_at IS NULL")
                ).scalar_one(),
                "global.timeline_count": db.execute(
                    text("""
                      SELECT (SELECT count(*) FROM social_posts) +
                             (SELECT count(*) FROM social_stories) +
                             (SELECT count(*) FROM activities WHERE activity_type NOT IN ('wechat_direct_summary','wechat_group_summary'))
                    """)
                ).scalar_one(),
                f"provider.{payload.get('source', 'unknown')}.coverage": db.execute(
                    text("""
                      SELECT count(DISTINCT (stream,external_id)) FROM source_observations
                      WHERE source = :source AND state IN ('new', 'changed', 'unchanged')
                    """),
                    {"source": payload.get("source")},
                ).scalar_one(),
            } if refresh_global else {}
            for metric_key, value in metrics.items():
                db.execute(text("""
                  INSERT INTO global_metric_snapshots(metric_key, value_json, source_watermark, freshness_state)
                  VALUES (:metric_key, CAST(:value AS jsonb), :watermark, 'fresh')
                """), {"metric_key": metric_key, "value": str(value), "watermark": watermark})
            for profile_id in payload.get("affected_profiles", []):
                profile_timeline = db.execute(
                    text("""
                      SELECT (SELECT count(*) FROM social_posts WHERE profile_id = :profile_id) +
                             (SELECT count(*) FROM social_stories WHERE profile_id = :profile_id) +
                             (SELECT count(*) FROM activity_participants ap JOIN activities a ON a.id=ap.activity_id
                              WHERE ap.profile_id = :profile_id AND a.activity_type NOT IN ('wechat_direct_summary','wechat_group_summary'))
                    """),
                    {"profile_id": profile_id},
                ).scalar_one()
                identity_count = db.execute(
                    text("SELECT count(*) FROM identities WHERE profile_id = :profile_id AND status = 'active'"),
                    {"profile_id": profile_id},
                ).scalar_one()
                for metric_key, value in {
                    "timeline.count": profile_timeline,
                    "identity.count": identity_count,
                }.items():
                    db.execute(
                        text("""
                          INSERT INTO profile_metrics_current
                            (profile_id, metric_key, value_json, source_watermark, computed_at, freshness_state)
                          VALUES (:profile_id, :metric_key, CAST(:value AS jsonb), :watermark, now(), 'fresh')
                          ON CONFLICT (profile_id, metric_key) DO UPDATE SET
                            value_json = EXCLUDED.value_json,
                            source_watermark = EXCLUDED.source_watermark,
                            computed_at = EXCLUDED.computed_at,
                            freshness_state = EXCLUDED.freshness_state
                        """),
                        {
                            "profile_id": profile_id,
                            "metric_key": metric_key,
                            "value": str(value),
                            "watermark": watermark,
                        },
                    )


def run(poll_seconds: float = 2.0):
    last_media_check=0
    while True:
        if time.monotonic()-last_media_check>300:
            with engine.begin() as db:enqueue_due_media(db)
            last_media_check=time.monotonic()
        job = claim_job()
        if not job:
            time.sleep(poll_seconds)
            continue
        try:
            execute_job(job)
        except Exception as exc:  # noqa: BLE001 - the worker must record and continue
            terminal=False
            if job['job_type']=='media.download':
                from urllib.error import HTTPError
                reason=f'HTTP {exc.code}' if isinstance(exc,HTTPError) else type(exc).__name__
                terminal=isinstance(exc,HTTPError) and exc.code in (401,403,404,410)
                with engine.begin() as db:
                    media_state(db,job['payload'],'expired' if isinstance(exc,HTTPError) and exc.code in (401,403,404,410) else 'failed',reason)
            finish_job(job["id"], str(exc),terminal)
        else:
            finish_job(job["id"])


if __name__ == "__main__":
    run()
