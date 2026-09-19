"""Serial, source-specific archive refreshes without a global migration backfill."""
import json
import os
import sqlite3
import time
from pathlib import Path

from sqlalchemy import text

from .archive_media import instagram_archive, moments_cache
from .db import SessionLocal, engine
from .import_messages import ingest
from .reconcile_sources import instagram, instagram_profiles, moments


def signature(paths):
    return [(str(p),p.stat().st_size,p.stat().st_mtime_ns) for p in paths if p.is_file()]


def cycle():
    source=Path(os.environ.get('CHATLOG_DB_ROOT','/data/chatlog'))
    staging=Path(os.environ.get('STAGING_ROOT','/data/staging'))
    media=Path(os.environ.get('MEDIA_ROOT','/data/media'))
    cache=Path(os.environ.get('SNS_CACHE_ROOT','/data/sns-cache'))
    instagram_root=staging/'instagram-current'
    snapshots=staging/'continuous-snapshots';snapshots.mkdir(parents=True,exist_ok=True)
    state_file=snapshots/'state.json';state=json.loads(state_file.read_text()) if state_file.exists() else {}
    next_state=dict(state)
    # Compare source files; write a consistent SQLite backup only when changed.
    for kind,paths in [('moments',[source/'sns/sns.db']),('messages',sorted((source/'message').glob('message_[0-9]*.db')))]:
        stamp=signature(paths+[Path(str(p)+'-wal') for p in paths])
        if not stamp or state.get(kind)==[list(x) for x in stamp]:continue
        destination=snapshots/kind;destination.mkdir(exist_ok=True)
        for path in paths:
            if not path.is_file():continue
            with sqlite3.connect(f'file:{path}?mode=ro',uri=True) as original,sqlite3.connect(destination/path.name) as snapshot:
                original.backup(snapshot)
        with SessionLocal() as db:
            if kind=='moments':
                report=moments(db,destination/'sns.db',apply=True)
                report['media']=moments_cache(db,destination/'sns.db',cache,media)
            else:
                with engine.connect() as lease:
                    if not lease.execute(text('SELECT pg_try_advisory_lock(11803292)')).scalar_one():continue
                    lease.commit()
                    try:report=ingest(db,destination)
                    finally:lease.execute(text('SELECT pg_advisory_unlock(11803292)'));lease.commit()
        print(json.dumps({'source':kind,**report}),flush=True);next_state[kind]=stamp
        temporary=state_file.with_suffix('.tmp');temporary.write_text(json.dumps(next_state));temporary.replace(state_file)
    stamp=signature([instagram_root/'.crm-ready'])
    if stamp and state.get('instagram')!=[list(x) for x in stamp]:
        with SessionLocal() as db:
            report=instagram(db,instagram_root/'profiles',apply=True)
            report['profiles']=instagram_profiles(db,instagram_root/'profiles',apply=True)
            report['media']=instagram_archive(db,instagram_root/'profiles',media)
            print(json.dumps({'source':'instagram',**report}),flush=True)
        next_state['instagram']=stamp
    temporary=state_file.with_suffix('.tmp');temporary.write_text(json.dumps(next_state));temporary.replace(state_file)


def main():
    interval=max(int(os.environ.get('ARCHIVE_SYNC_SECONDS','21600')),3600)
    while True:
        try:cycle()
        except Exception as exc:  # noqa: BLE001 - retain the last good watermark and retry later
            print(json.dumps({'archive_sync_error':type(exc).__name__}),flush=True)
        time.sleep(interval)


if __name__=='__main__':main()
