"""One-shot migration of the existing Monica/Chatlog archives.

The source archives are deliberately kept outside PostgreSQL.  This command
normalizes the useful current projections into the API schema, while retaining
the original JSON/SQLite files under ``RAW_ROOT`` for replay and audit.  It is
safe to run again: import batches are idempotent and direct projections use
stable source record IDs/upserts.

The command is intended for the NAS image:

    uv run python -m app.full_migration --source-root /data/staging/import-source

It does not fetch anything from a provider and never needs provider login
credentials.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import xml.etree.ElementTree as ET
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from .bulk_moments import project_moments
from .content import get_or_create_content
from .db import SessionLocal, migrate
from .identity_rules import monica_identities
from .imports import project_batch
from .remote_media import enqueue_media
from .repositories import append_field_revision
from .schemas import ImportBatchRequest


def now() -> datetime:
    return datetime.now(UTC)


def iso(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        # WeChat/SQLite timestamps are Unix seconds.
        try:
            return datetime.fromtimestamp(value, UTC).isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    value = str(value).strip()
    if not value:
        return None
    # Chatlog exports timestamps as strings even though they are Unix
    # seconds. Treat them exactly like the integer form instead of silently
    # dropping every Moments date.
    if value.isdigit() or (value.startswith("-") and value[1:].isdigit()):
        try:
            return datetime.fromtimestamp(int(value), UTC).isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    try:
        return datetime.fromisoformat(value).isoformat()
    except ValueError:
        return None


def json_load(path: Path) -> Any:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def find_file(root: Path, *names: str) -> Path | None:
    for name in names:
        direct = root / name
        if direct.is_file():
            return direct
    for name in names:
        matches = sorted(root.rglob(name))
        if matches:
            return matches[0]
    return None


def find_directory(root: Path, name: str) -> Path | None:
    """Find an archive directory even when the source was copied as a bundle."""
    direct = root / name
    if direct.is_dir():
        return direct
    matches = sorted(path for path in root.rglob(name) if path.is_dir())
    return matches[0] if matches else None


def ndjson(path: Path | None) -> list[dict[str, Any]]:
    if not path or not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                # A malformed source row must not discard the rest of an
                # export. The original file remains available for audit.
                continue
    return rows


def chunks(values: list[Any], size: int = 500) -> Iterable[list[Any]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def record_digest(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def run_batch(
    db: Session,
    *,
    source: str,
    stream: str,
    records: list[dict[str, Any]],
    batch_name: str,
    chunk_size: int = 500,
) -> None:
    """Run a normalized API batch in bounded transactions."""
    stamp = now()
    observation = __import__("uuid").uuid4().hex if source == "linkedin" and stream in {"profiles", "posts"} else ""
    if not records:
        # An empty batch still documents a checked source stream and its cursor.
        records = []
    total = max(1, (len(records) + chunk_size - 1) // chunk_size)
    for index, part in enumerate(chunks(records, chunk_size) or [[]]):
        batch_id = f"{batch_name}-{index + 1:04d}-of-{total:04d}-{record_digest(part)[:16]}"
        if observation:
            batch_id += "-" + observation
        request = ImportBatchRequest(
            source=source,
            stream=stream,
            schema_version=1,
            batch_id=batch_id,
            idempotency_key=f"{source}:{stream}:{batch_id}",
            cursor_before=str(index) if index else None,
            cursor_after=str(index + 1),
            observed_at=stamp,
            records=part,
        )
        if source == "wechat" and stream == "moments":
            project_moments(db, request)
        else:
            project_batch(db, request)
        db.commit()
        if stream == "moments":
            print(f"Moments {batch_id}: {len(part)} records committed", flush=True)


def profile_map(db: Session, provider: str) -> dict[str, str]:
    rows = db.execute(
        text(
            """SELECT i.external_id,i.profile_id FROM identities i JOIN profiles p ON p.id=i.profile_id
            WHERE i.provider=:provider AND i.status NOT IN ('invalid','merged') AND p.archived_at IS NULL
            AND p.profile_type=CASE WHEN :provider='wechat_group' THEN 'group' ELSE 'person' END"""
        ),
        {"provider": provider},
    ).mappings()
    return {str(row["external_id"]): str(row["profile_id"]) for row in rows}


def upsert_identity(
    db: Session,
    *,
    provider: str,
    external_id: str,
    profile_id: str | None,
    username: str | None = None,
    profile_url: str | None = None,
    display_name: str | None = None,
    status: str = "active",
) -> None:
    if not external_id:
        return
    from .source_projection import enabled
    actual_provider='wechat' if provider=='wechat_group' else provider
    if enabled(db,actual_provider):
        from .platform_migrate import account_lookup, resolve_account
        _,aliases,profiles=account_lookup(db,actual_provider)
        aid=resolve_account(actual_provider,external_id,'',profile_id,aliases,profiles)
        if not aid:return
        profile_id=db.execute(text('SELECT profile_id FROM source_account_links WHERE account_id=:id'),{'id':aid}).scalar_one_or_none()
        db.execute(text('''INSERT INTO identities(profile_id,provider,external_id,username,profile_url,display_name,status,source_account_id)
            VALUES(:profile,:provider,:external,:username,:url,:name,:status,:account)
            ON CONFLICT(provider,external_id) DO UPDATE SET profile_id=EXCLUDED.profile_id,source_account_id=EXCLUDED.source_account_id,
              username=COALESCE(EXCLUDED.username,identities.username),profile_url=COALESCE(EXCLUDED.profile_url,identities.profile_url),
              display_name=COALESCE(EXCLUDED.display_name,identities.display_name),last_seen_at=now()'''),
            {'profile':profile_id,'provider':provider,'external':external_id,'username':username,'url':profile_url,'name':display_name,'status':status,'account':aid})
        return
    db.execute(
        text("""
          INSERT INTO identities(profile_id, provider, external_id, username, profile_url, display_name, status)
          VALUES (:profile_id, :provider, :external_id, :username, :profile_url, :display_name, :status)
          ON CONFLICT(provider, external_id) DO UPDATE SET
            profile_id = COALESCE(identities.profile_id, EXCLUDED.profile_id),
            username = COALESCE(EXCLUDED.username, identities.username),
            profile_url = COALESCE(EXCLUDED.profile_url, identities.profile_url),
            display_name = COALESCE(EXCLUDED.display_name, identities.display_name),
            status = CASE WHEN EXCLUDED.profile_id IS NULL THEN identities.status ELSE EXCLUDED.status END,
            last_seen_at = now()
        """),
        {
            "profile_id": profile_id,
            "provider": provider,
            "external_id": external_id,
            "username": username,
            "profile_url": profile_url,
            "display_name": display_name,
            "status": status,
        },
    )


def relation_type(db: Session, name: str) -> str:
    return str(
        db.execute(
            text("""
              INSERT INTO relationship_types(name) VALUES (:name)
              ON CONFLICT(name) DO UPDATE SET name = EXCLUDED.name
              RETURNING id
            """),
            {"name": name},
        ).scalar_one()
    )


def add_relation(
    db: Session,
    *,
    from_id: str,
    to_id: str,
    type_id: str,
    source_type: str,
    note: str | None = None,
    confidence: float | None = None,
    source_record_id: str,
) -> None:
    if from_id == to_id:
        return
    edge = db.execute(
        text("""
          INSERT INTO relationship_edges
            (from_profile_id, to_profile_id, relationship_type_id, note, confidence, source_type)
          VALUES (:from_id, :to_id, :type_id, :note, :confidence, :source_type)
          ON CONFLICT(from_profile_id, to_profile_id, relationship_type_id) DO UPDATE SET
            note = COALESCE(EXCLUDED.note, relationship_edges.note),
            confidence = COALESCE(EXCLUDED.confidence, relationship_edges.confidence),
            source_type = EXCLUDED.source_type
          RETURNING id
        """),
        {
            "from_id": from_id,
            "to_id": to_id,
            "type_id": type_id,
            "note": note,
            "confidence": confidence,
            "source_type": source_type,
        },
    ).scalar_one()
    payload = json.dumps({"source_record_id": source_record_id, "note": note}, ensure_ascii=False)
    db.execute(
        text("""
          INSERT INTO relationship_edge_revisions(edge_id, operation, payload, source_type)
          SELECT :edge, 'created', CAST(:payload AS jsonb), :source_type
          WHERE NOT EXISTS (
            SELECT 1 FROM relationship_edge_revisions
            WHERE edge_id = :edge AND source_type = :source_type
              AND payload->>'source_record_id' = :source_record_id
          )
        """),
        {
            "edge": edge,
            "payload": payload,
            "source_type": source_type,
            "source_record_id": source_record_id,
        },
    )


def add_tag(
    db: Session, *, name: str, profile_id: str, source_type: str, source_record_id: str
) -> None:
    if not name:
        return
    tag_id = db.execute(
        text("""
          INSERT INTO tags(name) VALUES (:name)
          ON CONFLICT(name) DO UPDATE SET name = EXCLUDED.name RETURNING id
        """),
        {"name": str(name)[:255]},
    ).scalar_one()
    db.execute(
        text("""
          INSERT INTO tag_memberships(tag_id, profile_id, source_type)
          VALUES (:tag, :profile, :source_type)
          ON CONFLICT(tag_id, profile_id) DO UPDATE SET source_type = EXCLUDED.source_type
        """),
        {"tag": tag_id, "profile": profile_id, "source_type": source_type},
    )
    db.execute(
        text("""
          INSERT INTO tag_membership_revisions(tag_id, profile_id, operation, source_type)
          SELECT :tag, :profile, 'added', :source_type
          WHERE NOT EXISTS (
            SELECT 1 FROM tag_membership_revisions
            WHERE tag_id = :tag AND profile_id = :profile
              AND source_type = :source_type AND operation = 'added'
          )
        """),
        {"tag": tag_id, "profile": profile_id, "source_type": source_type},
    )


def add_activity(
    db: Session,
    *,
    activity_type: str,
    occurred_at: Any,
    title: str,
    body: Any,
    source_type: str,
    source_record_id: str,
    profile_ids: Iterable[str] = (),
) -> None:
    at = iso(occurred_at) or now().isoformat()
    row = db.execute(
        text("""
          INSERT INTO activities(activity_type, occurred_at, title, body, source_type, source_record_id)
          SELECT :activity_type, :occurred_at, :title, :body, :source_type, :source_record_id
          WHERE NOT EXISTS (
            SELECT 1 FROM activities WHERE source_type = :source_type AND source_record_id = :source_record_id
          ) RETURNING id
        """),
        {
            "activity_type": activity_type,
            "occurred_at": at,
            "title": title[:255],
            "body": json.dumps(body, ensure_ascii=False) if not isinstance(body, str) else body,
            "source_type": source_type,
            "source_record_id": source_record_id,
        },
    ).scalar_one_or_none()
    if not row:
        row = db.execute(
            text(
                "SELECT id FROM activities WHERE source_type = :source_type AND source_record_id = :source_record_id"
            ),
            {"source_type": source_type, "source_record_id": source_record_id},
        ).scalar_one()
    for profile_id in profile_ids:
        if profile_id:
            db.execute(
                text("""
                  INSERT INTO activity_participants(activity_id, profile_id)
                  VALUES (:activity, :profile) ON CONFLICT DO NOTHING
                """),
                {"activity": row, "profile": profile_id},
            )


def contact_name(contact: dict[str, Any]) -> str:
    parts = [contact.get("first_name"), contact.get("middle_name"), contact.get("last_name")]
    name = " ".join(str(part).strip() for part in parts if part not in (None, ""))
    return name or str(contact.get("nickname") or contact.get("id") or "未命名联系人")


def load_monica(db: Session, root: Path) -> dict[str, str]:
    """Import Monica's normalized database export and return old-id mapping."""
    export = find_directory(root, "monica_db_export")
    if not export:
        return {}
    contacts = ndjson(export / "contacts.ndjson")
    field_types = {
        str(row["id"]): str(row.get("name") or f"field-{row['id']}")
        for row in ndjson(export / "contact_field_types.ndjson")
    }
    fields_by_contact: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for row in ndjson(export / "contact_fields.ndjson"):
        fields_by_contact[str(row["contact_id"])][
            field_types.get(str(row["type_id"]), str(row["type_id"]))
        ].append(str(row.get("data") or ""))

    records: list[dict[str, Any]] = []
    for contact in contacts:
        contact_id = str(contact["id"])
        custom = {name: values for name, values in fields_by_contact.get(contact_id, {}).items()}
        fields: dict[str, Any] = {"monica.custom_fields": custom}
        if contact.get("description"):
            fields["biography"] = contact["description"]
        if contact.get("job"):
            fields["job"] = contact["job"]
        if contact.get("company"):
            fields["company"] = contact["company"]
        records.append(
            {
                "external_id": f"contact:{contact_id}",
                "content": {
                    "display_name": contact_name(contact),
                    "summary": contact.get("description"),
                    "fields": fields,
                    "monica_contact_id": contact_id,
                    "nickname": contact.get("nickname"),
                    "job": contact.get("job"),
                    "company": contact.get("company"),
                    "address": custom.get("地址") or custom.get("Address"),
                    "employment": (
                        [{"company": contact.get("company"), "title": contact.get("job")}]
                        if contact.get("company") or contact.get("job")
                        else []
                    ),
                    "avatar_external_url": contact.get("avatar_external_url"),
                },
            }
        )
    run_batch(db, source="monica", stream="contacts", records=records, batch_name="full-contacts")
    mapping = {
        str(row["external_id"]).split(":", 1)[1]: str(row["profile_id"])
        for row in db.execute(
            text(
                "SELECT external_id, profile_id FROM identities WHERE provider='monica' AND external_id LIKE 'contact:%' AND profile_id IS NOT NULL"
            )
        ).mappings()
    }

    # Preserve Monica's source identities in the provider-specific identity table.
    for contact in contacts:
        cid = str(contact["id"])
        profile_id = mapping.get(cid)
        if not profile_id:
            continue
        for provider, value, kind in monica_identities(fields_by_contact.get(cid, {})):
            # Aliases are fields; stable IDs/confirmed social URLs are identity evidence.
            if kind == "alias":
                continue
            url = (f"https://www.linkedin.com/in/{value}" if provider == "linkedin" else
                   f"https://www.instagram.com/{value}/" if provider == "instagram" else None)
            upsert_identity(db, provider=provider, external_id=value, profile_id=profile_id,
                            username=value, profile_url=url, display_name=contact_name(contact))
        db.execute(
            text("UPDATE profiles SET summary = COALESCE(summary, :summary) WHERE id = :id"),
            {"summary": contact.get("description"), "id": profile_id},
        )

    type_map = {
        str(row["id"]): str(row.get("name") or row["id"])
        for row in ndjson(export / "relationship_types.ndjson")
    }
    for row in ndjson(export / "relationships.ndjson"):
        from_id = mapping.get(str(row["contact_is"]))
        to_id = mapping.get(str(row["of_contact"]))
        if from_id and to_id:
            add_relation(
                db,
                from_id=from_id,
                to_id=to_id,
                type_id=relation_type(
                    db, type_map.get(str(row["relationship_type_id"]), "Monica relationship")
                ),
                source_type="monica",
                source_record_id=f"relationship:{row['id']}",
            )
    tag_names = {
        str(row["id"]): str(row.get("name") or "未命名标签")
        for row in ndjson(export / "tags.ndjson")
    }
    for row in ndjson(export / "contact_tag.ndjson"):
        profile_id = mapping.get(str(row["contact_id"]))
        tag_name = tag_names.get(str(row["tag_id"]))
        if profile_id and tag_name:
            add_tag(
                db,
                name=tag_name,
                profile_id=profile_id,
                source_type="monica",
                source_record_id=f"contact-tag:{row['contact_id']}:{row['tag_id']}",
            )
    for filename, kind, title_key in (
        ("notes.ndjson", "note", "Monica note"),
        ("tasks.ndjson", "task", "Monica task"),
        ("reminders.ndjson", "reminder", "Monica reminder"),
        ("calls.ndjson", "call", "Monica call"),
        ("activities.ndjson", "activity", "Monica activity"),
    ):
        for row in ndjson(export / filename):
            profile_id = mapping.get(str(row.get("contact_id")))
            title = str(row.get("title") or row.get("summary") or title_key)
            body = row.get("body") or row.get("description") or row.get("content") or row
            add_activity(
                db,
                activity_type=kind,
                occurred_at=row.get("happened_at")
                or row.get("called_at")
                or row.get("initial_date")
                or row.get("created_at"),
                title=title,
                body=body,
                source_type="monica",
                source_record_id=f"{kind}:{row.get('id')}",
                profile_ids=[profile_id] if profile_id else [],
            )
    db.commit()
    return mapping


def wechat_content(
    person: dict[str, Any], direct: dict[str, Any], group: dict[str, Any]
) -> dict[str, Any]:
    wxid = str(person.get("username") or person.get("u") or "")
    fields: dict[str, Any] = {}
    for key, field_key in (
        ("alias", "wechat.alias"),
        ("remark", "wechat.remark"),
        ("nick_name", "wechat.nickname"),
        ("signature", "wechat.signature"),
        ("add_source_label", "wechat.add_source"),
        ("profile_country", "wechat.country"),
        ("profile_province", "wechat.province"),
        ("profile_city", "wechat.city"),
        ("historical_nicknames", "wechat.historical_nicknames"),
    ):
        if person.get(key) not in (None, "", []):
            fields[field_key] = person[key]
    if direct:
        fields["wechat.direct_stats"] = direct
    if group:
        fields["wechat.group_stats"] = group
    return {
        "display_name": person.get("remark")
        or person.get("nick_name")
        or person.get("nick")
        or person.get("display_name")
        or wxid,
        "summary": person.get("signature"),
        "username": wxid,
        "profile_url": person.get("big_head_url"),
        # Keep provider URLs in the versioned field projection.  The import
        # materializer can turn them into content-addressed NAS media while
        # still retaining the original URL for provenance and replay.
        "fields": {
            **fields,
            **({"wechat.avatar_url": person.get("big_head_url") or person.get("small_head_url")}
               if person.get("big_head_url") or person.get("small_head_url") else {}),
            **({"wechat.moments_cover_url": person.get("moments_cover_url")}
               if person.get("moments_cover_url") else {}),
        },
        "avatar_url": person.get("big_head_url") or person.get("small_head_url"),
        "moments_cover_url": person.get("moments_cover_url"),
    }


def load_wechat(
    db: Session, root: Path, monica_map: dict[str, str]
) -> tuple[dict[str, str], dict[str, str]]:
    path = find_file(root, "chatlog_extract.json")
    data = json_load(path) if path else {}
    group_path = find_file(root, "group_import_payload.json")
    group_data = json_load(group_path) if group_path else {}
    people: dict[str, dict[str, Any]] = {}
    for item in (data.get("contacts") or []) + (group_data.get("people") or []):
        wxid = str(item.get("username") or item.get("u") or "")
        if wxid and not wxid.endswith("@chatroom"):
            people.setdefault(wxid, item)
            people[wxid].update({k: v for k, v in item.items() if v not in (None, "", [], {})})
    known_people = profile_map(db, "wechat")
    direct = data.get("direct") or {}
    records = []
    for wxid, person in people.items():
        profile_id = known_people.get(wxid)
        records.append(
            {
                "external_id": wxid,
                "profile_id": profile_id,
                "content": wechat_content(
                    person, direct.get(wxid) or {}, person.get("group") or {}
                ),
            }
        )
    run_batch(db, source="wechat", stream="contacts", records=records, batch_name="full-contacts")
    wechat_map = profile_map(db, "wechat")

    rooms = group_data.get("rooms") or data.get("rooms") or []
    room_records = []
    room_stats = data.get("room_activity") or {}
    for room in rooms:
        room_id = str(room.get("id") or room.get("username") or room.get("name") or "")
        if not room_id:
            continue
        room_records.append(
            {
                "external_id": room_id,
                "content": {
                    "profile_type": "group",
                    "display_name": room.get("label") or room.get("name") or room_id,
                    "summary": room.get("tag_name"),
                    "fields": {
                        "wechat.group_id": room_id,
                        "wechat.member_count": room.get("member_count"),
                        "wechat.owner": room.get("owner"),
                        "wechat.group_stats": room_stats.get(room_id) or {},
                    },
                },
            }
        )
    run_batch(db, source="wechat", stream="groups", records=room_records, batch_name="full-groups")
    group_map = profile_map(db, "wechat_group")

    memberships = group_data.get("memberships") or {}
    for person_wxid, room_ids in memberships.items():
        person_id = wechat_map.get(str(person_wxid))
        if not person_id:
            continue
        for room_id in room_ids or []:
            group_id = group_map.get(str(room_id))
            if not group_id:
                continue
            db.execute(
                text("""
              INSERT INTO group_memberships(group_profile_id, person_profile_id, observed_at, source_record_id)
              VALUES (:group_id, :person_id, now(), :source_record_id)
              ON CONFLICT(group_profile_id, person_profile_id) DO UPDATE SET observed_at = now(), source_record_id = EXCLUDED.source_record_id
            """),
                {
                    "group_id": group_id,
                    "person_id": person_id,
                    "source_record_id": f"membership:{room_id}:{person_wxid}",
                },
            )

    # Conversation rows and monthly summaries keep the overview fast while the
    # original message SQLite remains available for a future body-level parser.
    for wxid, summary in direct.items():
        profile_id = wechat_map.get(str(wxid))
        if not profile_id:
            continue
        db.execute(
            text("""
          INSERT INTO conversations(conversation_type, profile_id, external_id)
          VALUES ('direct', :profile_id, :external_id)
          ON CONFLICT(conversation_type, external_id) DO UPDATE SET profile_id = EXCLUDED.profile_id
        """),
            {"profile_id": profile_id, "external_id": f"direct:{wxid}"},
        )
        add_activity(
            db,
            activity_type="wechat_direct_summary",
            occurred_at=summary.get("last"),
            title="微信私聊统计",
            body=summary,
            source_type="wechat",
            source_record_id=f"direct-summary:{wxid}",
            profile_ids=[profile_id],
        )
    for room_id, summary in room_stats.items():
        group_id = group_map.get(str(room_id))
        if not group_id:
            continue
        db.execute(
            text("""
          INSERT INTO conversations(conversation_type, profile_id, external_id)
          VALUES ('group', :profile_id, :external_id)
          ON CONFLICT(conversation_type, external_id) DO UPDATE SET profile_id = EXCLUDED.profile_id
        """),
            {"profile_id": group_id, "external_id": f"group:{room_id}"},
        )
        add_activity(
            db,
            activity_type="wechat_group_summary",
            occurred_at=summary.get("last"),
            title="微信群统计",
            body=summary,
            source_type="wechat",
            source_record_id=f"group-summary:{room_id}",
            profile_ids=[group_id],
        )
    db.commit()
    return wechat_map, group_map


def load_instagram(db: Session, root: Path, monica_map: dict[str, str]) -> None:
    path = find_file(root, "instagram_profiles.json")
    data = json_load(path) if path else {}
    records = []
    for item in data.get("profiles", []):
        provider_id = str(
            item.get("provider_user_id") or item.get("username") or item.get("profile_url") or ""
        )
        if not provider_id:
            continue
        profile_id = monica_map.get(str(item.get("contact_id")))
        records.append(
            {
                "external_id": provider_id,
                "profile_id": profile_id,
                "content": {
                    "display_name": item.get("full_name") or item.get("username") or provider_id,
                    "username": item.get("username"),
                    "profile_url": item.get("profile_url"),
                    "summary": item.get("biography"),
                    "fields": {
                        key: item.get(key)
                        for key in (
                            "biography",
                            "external_url",
                            "is_private",
                            "is_verified",
                            "followers_count",
                            "followees_count",
                            "media_count",
                            "last_post_at",
                            "profile_pic_url",
                            "archived_at",
                            "match_note",
                        )
                        if item.get(key) not in (None, "")
                    },
                },
            }
        )
    run_batch(
        db, source="instagram", stream="profiles", records=records, batch_name="full-profiles"
    )
    # Add a stable username identity as well as provider numeric ID when both exist.
    for item in data.get("profiles", []):
        provider_id = str(
            item.get("provider_user_id") or item.get("username") or item.get("profile_url") or ""
        )
        profile_id = monica_map.get(str(item.get("contact_id"))) or profile_map(
            db, "instagram"
        ).get(provider_id)
        if profile_id and item.get("username"):
            upsert_identity(
                db,
                provider="instagram",
                external_id=f"username:{item['username']}",
                profile_id=profile_id,
                username=item["username"],
                profile_url=item.get("profile_url"),
                display_name=item.get("full_name"),
            )
    instagram_map = profile_map(db, 'instagram')
    posts=[]
    for item in data.get('posts', []):
        profile_id=monica_map.get(str(item.get('contact_id'))) or instagram_map.get(str(item.get('provider_user_id')))
        posts.append({'external_id':str(item.get('external_id') or item.get('shortcode')),
                      'source_account_external_id':str(item.get('provider_user_id') or ''),
                      'entity_type':'post','profile_id':profile_id,'occurred_at':iso(item.get('occurred_at')),
                      'content':{'text':item.get('caption'),'like_count':item.get('like_count') or 0,
                                 'comment_count':item.get('comment_count') or 0,'location':item.get('location'),
                                 'permalink':item.get('permalink'),'shortcode':item.get('shortcode'),'media':item.get('media') or []}})
    run_batch(db,source='instagram',stream='posts',records=posts,batch_name='archive-posts-v1')
    # Current archive contains profiles but no durable Story archive.  Keep this
    # coverage fact explicit so the UI never turns absence into "no stories".
    db.execute(
        text("""
      INSERT INTO global_metric_snapshots(metric_key, value_json, source_watermark, freshness_state)
      VALUES ('coverage.instagram', CAST(:value AS jsonb), :watermark, 'partial')
    """),
        {
            "value": json.dumps(
                {
                    "profiles": len(data.get("profiles", [])),
                    "posts": len(posts),
                    "stories": "unavailable",
                    "status": "partial",
                }
            ),
            "watermark": str(data.get("generated_at") or now().isoformat()),
        },
    )
    db.commit()


def linkedin_profile_content(item: dict[str, Any]) -> dict[str, Any]:
    profile = item.get("profile") or {}
    experiences = profile.get("experiences") or []
    educations = profile.get("educations") or []
    location = profile.get("location")
    fields: dict[str, Any] = {}
    for key, value in (
        ("linkedin.about", profile.get("about")),
        ("linkedin.open_to_work", profile.get("open_to_work")),
        ("linkedin.headline", profile.get("headline")),
        ("linkedin.profile_url", item.get("profile_url")),
        ("linkedin.mutuals", item.get("mutuals")),
        ("linkedin.partial", item.get("partial")),
        (
            "linkedin.avatar_url",
            profile.get("avatar_url")
            or profile.get("profile_image_url")
            or profile.get("image_url")
            or profile.get("photo_url"),
        ),
    ):
        if value not in (None, "", []):
            fields[key] = value
    return {
        "display_name": profile.get("name")
        or item.get("provider_user_id")
        or item.get("profile_url")
        or "LinkedIn profile",
        "summary": profile.get("about"),
        "profile_url": item.get("profile_url"),
        "fields": fields,
        "address": location,
        "employment": experiences,
        "education": educations,
        "avatar_url": profile.get("avatar_url")
        or profile.get("profile_image_url")
        or profile.get("image_url")
        or profile.get("photo_url"),
    }


def _linkedin_media(post: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize LinkedIn's image URL list into the common timeline shape."""
    rows: list[dict[str, Any]] = []
    urls = post.get("image_urls") or post.get("images") or []
    if isinstance(urls, str):
        urls = [urls]
    if not isinstance(urls, list):
        return rows
    for index, url in enumerate(urls):
        if isinstance(url, dict):
            url = url.get("url") or url.get("source_url") or url.get("image_url")
        if not isinstance(url, str) or not url.strip():
            continue
        rows.append(
            {
                "role": f"media-{index + 1}",
                "media_type": "image",
                "source_url": url.strip(),
                "thumbnail_url": url.strip(),
            }
        )
    return rows


def load_linkedin(db: Session, root: Path, monica_map: dict[str, str]) -> None:
    path = root if root.is_file() else find_file(root, "linkedin_enrichment.incoming.json")
    data = json_load(path) if path else {}
    records = []
    for item in data.get("profiles", []):
        provider_id = str(item.get("provider_user_id") or item.get("profile_url") or "")
        if not provider_id:
            continue
        records.append(
            {
                "external_id": provider_id,
                "profile_id": monica_map.get(str(item.get("contact_id"))),
                "content": linkedin_profile_content(item),
            }
        )
    run_batch(db, source="linkedin", stream="profiles", records=records,
              batch_name="profiles-media-v3-" + record_digest(records)[:20])
    db.execute(text("""
        UPDATE social_posts p SET external_id = co.payload_json->>'provider_post_id'
        FROM content_objects co WHERE co.id = p.content_object_id AND p.provider = 'linkedin'
            AND NULLIF(co.payload_json->>'provider_post_id', '') IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM social_posts other WHERE other.provider = 'linkedin'
                AND other.external_id = co.payload_json->>'provider_post_id' AND other.id <> p.id)
    """))
    linkedin_map = profile_map(db, "linkedin")
    for item in data.get("profiles", []):
        provider_id = str(item.get("provider_user_id") or item.get("profile_url") or "")
        profile_id = monica_map.get(str(item.get("contact_id"))) or linkedin_map.get(provider_id)
        from .source_projection import enabled
        if not profile_id and not enabled(db,'linkedin'):
            continue
        upsert_identity(
            db,
            provider="linkedin",
            external_id=provider_id,
            profile_id=profile_id,
            profile_url=item.get("profile_url"),
            display_name=(item.get("profile") or {}).get("name"),
        )
        snapshots = sorted(
            item.get("snapshots") or [], key=lambda row: str(row.get("captured_at") or "")
        )
        snapshot_records = []
        for index, snapshot in enumerate(snapshots):
            snapshot_id = f"{provider_id}:{snapshot.get('hash') or index}"
            snapshot_records.append(
                {
                    "external_id": snapshot_id,
                    "profile_id": profile_id,
                    "content": {
                        "fields": {
                            "linkedin.snapshot": snapshot.get("payload") or snapshot,
                            "linkedin.snapshot_hash": snapshot.get("hash"),
                            "linkedin.snapshot_status": {
                                "partial": snapshot.get("partial"),
                                "kind": snapshot.get("kind"),
                            },
                        }
                    },
                    "source_updated_at": iso(snapshot.get("captured_at")),
                }
            )
        if snapshot_records:
            run_batch(
                db,
                source="linkedin",
                stream="snapshots",
                records=snapshot_records,
                batch_name=f"snapshots-{provider_id[:32]}-{record_digest(snapshot_records)[:16]}",
                chunk_size=250,
            )
        posts = []
        for post in item.get("posts") or []:
            posts.append({**post, "profile_id": profile_id, "provider": "linkedin"})
        if posts:
            normalized = []
            for post in posts:
                media = _linkedin_media(post)
                normalized.append(
                    {
                        "external_id": str(
                            post.get("provider_post_id") or post.get("urn") or post.get("external_id") or post.get("id") or post.get("source_key") or record_digest(post)
                        ),
                        "profile_id": profile_id,
                        "source_account_external_id": provider_id,
                        "provider": "linkedin",
                        "entity_type": "post",
                        "occurred_at": iso(post.get("occurred_at") or post.get("posted_at") or post.get("created_at")),
                        "content": {
                            **post,
                            "media": media,
                            "like_count": post.get("reaction_count"),
                            "comment_count": post.get("comment_count"),
                        },
                        "media": media,
                    }
                )
            run_batch(
                db,
                source="linkedin",
                stream="posts",
                records=normalized,
                batch_name=f"posts-media-v3-{provider_id[:32]}-{record_digest(normalized)[:16]}",
            )
    db.execute(
        text("""
      INSERT INTO global_metric_snapshots(metric_key, value_json, source_watermark, freshness_state)
      VALUES ('coverage.linkedin', CAST(:value AS jsonb), :watermark, 'fresh')
    """),
        {
            "value": json.dumps(
                {
                    "profiles": len(data.get("profiles", [])),
                    "posts": sum(len(x.get("posts") or []) for x in data.get("profiles", [])),
                    "status": "partial"
                    if any(x.get("partial") for x in data.get("profiles", []))
                    else "fresh",
                }
            ),
            "watermark": str(data.get("generated_at") or now().isoformat()),
        },
    )
    db.commit()


def load_moments_and_relationships(db: Session, root: Path, wechat_map: dict[str, str]) -> None:
    graph_path = find_file(root, "moments_graph.json")
    graph = json_load(graph_path) if graph_path else {}
    for node in graph.get("nodes", []):
        profile_id = wechat_map.get(str(node.get("u")))
        if not profile_id:
            continue
        append_field_revision(
            db,
            profile_id=profile_id,
            field_key="wechat.moments_summary",
            value={
                k: node.get(k)
                for k in ("label", "deg", "partners", "last", "community", "facts", "out", "in")
            },
            source_type="wechat",
            operation="import",
            source_record_id=f"moments-node:{node.get('u')}",
            observed_at=now(),
        )
    # Graph edge a/b values are array indexes, never WeChat identities. Keep
    # the raw graph as archive evidence; only post-level likes/comments create
    # the live interaction graph. Aggregates must not become confirmed people
    # relationships, even when a numeric legacy identity happens to match.
    locations_path = find_file(root, "moments_locations.json")
    locations = json_load(locations_path) if locations_path else {}
    for wxid, author in (locations.get("authors") or {}).items():
        profile_id = wechat_map.get(str(wxid))
        if profile_id:
            append_field_revision(
                db,
                profile_id=profile_id,
                field_key="wechat.location_history",
                value=author,
                source_type="wechat",
                operation="import",
                source_record_id=f"moments-locations:{wxid}",
                observed_at=now(),
            )
    tags_path = find_file(root, "moments_tags.json")
    tags = json_load(tags_path) if tags_path else {}
    for wxid, names in (tags.get("tags") or {}).items():
        profile_id = wechat_map.get(str(wxid))
        if profile_id:
            for name in names or []:
                add_tag(
                    db,
                    name=str(name),
                    profile_id=profile_id,
                    source_type="wechat",
                    source_record_id=f"moments-tag:{wxid}:{name}",
                )
    db.commit()


def load_wechat_interactions(db: Session, root: Path, wechat_map: dict[str, str]) -> None:
    money_path = find_file(root, "money_interactions.json")
    calls_path = find_file(root, "call_interactions.json")
    cards_path = find_file(root, "contact_card_relationships.json")
    for row in json_load(money_path).get("interactions", []) if money_path else []:
        counterparty = row.get("counterparty") or row.get("source_key")
        profile_id = wechat_map.get(str(counterparty))
        add_activity(
            db,
            activity_type="wechat_money",
            occurred_at=row.get("occurred_at") or row.get("settled_at"),
            title=f"微信资金往来 · {row.get('kind') or '记录'}",
            body=row,
            source_type="wechat",
            source_record_id=f"money:{row.get('source_key') or record_digest(row)}",
            profile_ids=[profile_id] if profile_id else [],
        )
    for row in json_load(calls_path).get("calls", []) if calls_path else []:
        source_key = row.get("source_key") or row.get("session")
        profile_id = wechat_map.get(str(source_key))
        add_activity(
            db,
            activity_type="wechat_call",
            occurred_at=row.get("occurred_at") or row.get("started_at"),
            title=f"微信通话 · {row.get('media_type') or 'call'}",
            body=row,
            source_type="wechat",
            source_record_id=f"call:{source_key or record_digest(row)}",
            profile_ids=[profile_id] if profile_id else [],
        )
    for row in json_load(cards_path).get("relationships", []) if cards_path else []:
        sender = wechat_map.get(str(row.get("sender")))
        recipient = wechat_map.get(str(row.get("card_username") or row.get("contact_username")))
        if sender and recipient:
            add_relation(
                db,
                from_id=sender,
                to_id=recipient,
                type_id=relation_type(db, "微信名片推荐"),
                source_type="wechat",
                note=json.dumps(row, ensure_ascii=False),
                source_record_id=f"contact-card:{row.get('source_key') or record_digest(row)}",
            )
    db.commit()


def _moments_media(obj: ET.Element) -> list[dict[str, Any]]:
    media_rows: list[dict[str, Any]] = []
    media_list = obj.find("ContentObject/mediaList")
    if media_list is None:
        return media_rows
    for index, media in enumerate(media_list.findall("media")):
        size = media.find("size")
        media_type = media.findtext("type") or ""
        source_url = media.findtext("url") or ""
        thumbnail_url = media.findtext("thumb") or ""
        if not source_url and not thumbnail_url:
            continue
        try:
            width = int(size.attrib.get("width", "0")) if size is not None else None
        except ValueError:
            width = None
        try:
            height = int(size.attrib.get("height", "0")) if size is not None else None
        except ValueError:
            height = None
        try:
            total_size = int(size.attrib.get("totalSize", "0")) if size is not None else None
        except ValueError:
            total_size = None
        try:
            duration = float(media.findtext("videoDuration") or "0")
            duration_ms = int(duration * 1000) if duration else None
        except ValueError:
            duration_ms = None
        url_element = media.find("url")
        media_rows.append(
            {
                "role": f"media-{index + 1}",
                "source_media_id": media.findtext("id"),
                "source_md5": url_element.attrib.get("md5") if url_element is not None else None,
                "media_type": "video" if media_type in {"6", "15"} else "image",
                "source_url": source_url or None,
                "thumbnail_url": thumbnail_url or None,
                "width": width,
                "height": height,
                "byte_length": total_size,
                "duration_ms": duration_ms,
                "description": media.findtext("description") or None,
            }
        )
    return media_rows


def _moments_interactions(root_node: ET.Element, post_id: str) -> list[dict[str, Any]]:
    local = root_node.find("LocalExtraInfo")
    if local is None:
        return []
    rows: list[dict[str, Any]] = []
    owner = root_node.findtext("TimelineObject/username")
    for list_name, default_type in (("like_user_list", "like"), ("comment_user_list", "comment"), ("with_user_list", "mention")):
        parent = local.find(list_name)
        if parent is None:
            continue
        for index, item in enumerate(parent.findall("user_comment")):
            ref_id = next((v for v in (item.findtext("ref_comment_64id"), item.findtext("ref_comment_id")) if v and v != "0"), "")
            interaction_type = default_type
            if default_type == "comment" and ref_id not in {"", "0"}:
                interaction_type = "reply"
            username = item.findtext("username") or ""
            create_time = item.findtext("create_time")
            if default_type == "mention" and create_time in {None, "", "0"}:
                create_time = root_node.findtext("TimelineObject/createTime")
            rows.append(
                {
                    "interaction_type": interaction_type,
                    # A reply remains the same source comment when its target
                    # becomes available; classification is not its identity.
                    "external_id": f"{post_id}:{default_type}:" + next((v for v in (item.findtext("comment_64id"), item.findtext("comment_id")) if v and v != "0"), f"{username}:{create_time or index}"),
                    "author_external_id": (owner if default_type == "mention" else username) or None,
                    "author_name": (None if default_type == "mention" else item.findtext("nickname")) or None,
                    "text": item.findtext("content") or None,
                    "occurred_at": iso(create_time),
                    "create_time": create_time,
                    "ref_external_id": ref_id or item.findtext("ref_comment_64id") or item.findtext("ref_comment_id") or None,
                    **({"ref_author_external_id": item.findtext("ref_username")} if ref_id else {}),
                    **({"target_external_id": username} if default_type == "mention" else {}),
                    "source": list_name,
                    "is_deleted": item.findtext("b_deleted") == "1",
                }
            )
    return rows


def load_moments_posts(
    db: Session, root: Path, wechat_map: dict[str, str], limit: int | None = None
) -> int:
    """Parse Chatlog's XML timeline table into searchable post records."""
    sqlite_path = find_file(root, "sns.db")
    if not sqlite_path:
        return 0
    connection = sqlite3.connect(str(sqlite_path))
    rows: list[dict[str, Any]] = []
    imported = 0
    batch_index = 0

    def flush() -> None:
        nonlocal rows, imported, batch_index
        if not rows:
            return
        batch_index += 1
        run_batch(
            db,
            source="wechat",
            stream="moments",
            records=rows,
            # A new idempotency namespace replays the corrected enrichment
            # projection without removing the earlier immutable revisions.
            batch_name=f"full-moments-v2-{batch_index:04d}",
            chunk_size=400,
        )
        imported += len(rows)
        rows = []

    try:
        cursor = connection.execute("SELECT tid, user_name, content FROM SnsTimeLine ORDER BY tid")
        for index, (tid, username, xml_text) in enumerate(cursor):
            if limit and index >= limit:
                break
            try:
                root_node = ET.fromstring(xml_text or "")
                obj = root_node.find("TimelineObject")
                if obj is None:
                    continue
                post_id = obj.findtext("id") or str(tid)
                create_time = obj.findtext("createTime")
                caption = obj.findtext("contentDesc") or ""
                location = obj.find("location")
                location_value = dict(location.attrib) if location is not None else None
                media = _moments_media(obj)
                interactions = _moments_interactions(root_node, post_id)
                content_object = {
                    "text": caption,
                    "username": username,
                    "occurred_at": iso(create_time),
                    "location": location_value,
                    "media": media,
                    "like_count": sum(item["interaction_type"] == "like" for item in interactions),
                    "comment_count": sum(item["interaction_type"] in {"comment", "reply"} for item in interactions),
                    "interaction_count": len(interactions),
                    "interactions": interactions,
                    "source_tid": str(tid),
                    "raw_xml_sha256": hashlib.sha256((xml_text or "").encode()).hexdigest(),
                }
                rows.append(
                    {
                        "external_id": post_id,
                        "profile_id": wechat_map.get(str(username)),
                        "provider": "wechat",
                        "entity_type": "post",
                        "occurred_at": iso(create_time),
                        "content": content_object,
                        # Metadata is preserved even when this archive does
                        # not contain a local byte for the remote CDN object.
                        "media": media,
                    }
                )
            except ET.ParseError:
                continue
            if len(rows) >= 400:
                flush()
    finally:
        connection.close()
    flush()
    # A 53k row timeline is committed in bounded batches. The API's content
    # hash and observation rules make retries cheap and preserve only changes.
    return imported


def import_media(db: Session, root: Path, media_root: Path) -> int:
    """Content-address existing avatar/media files without duplicating bytes."""
    source_dirs = [root / "avatars", root / "avatars-group", root / "covers", root / "media"]
    seen: set[str] = set()
    count = 0
    for source_dir in source_dirs:
        if not source_dir.is_dir():
            continue
        for source in source_dir.rglob("*"):
            if not source.is_file() or source.suffix.lower() in {".json", ".txt", ".ndjson"}:
                continue
            digest = hashlib.sha256()
            size = 0
            with source.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
                    size += len(chunk)
            sha = digest.hexdigest()
            if sha in seen:
                continue
            seen.add(sha)
            target = media_root / "sha256" / sha[:2] / sha[2:4] / sha
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                shutil.copy2(source, target)
            kind = (
                "image"
                if source.suffix.lower() in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic"}
                else "binary"
            )
            content_id, _ = get_or_create_content(
                db,
                value={"sha256": sha, "source_name": source.name},
                content_kind="media",
                storage_uri=str(target),
                store_payload=False,
            )
            db.execute(
                text("""
              INSERT INTO media_assets(content_object_id, sha256, media_type, byte_length, object_path, source_type, source_record_id)
              VALUES (:content_id, :sha, :media_type, :byte_length, :object_path, 'archive', :source_record_id)
              ON CONFLICT(sha256) DO UPDATE SET object_path = EXCLUDED.object_path
            """),
                {
                    "content_id": content_id,
                    "sha": sha,
                    "media_type": f"{kind}/{source.suffix.lstrip('.').lower() or 'octet-stream'}",
                    "byte_length": size,
                    "object_path": str(target),
                    "source_record_id": str(source),
                },
            )
            count += 1
    db.commit()
    return count


def link_profile_media(db: Session) -> int:
    """Attach imported avatar files to profiles using stable WeChat IDs.

    Archive filenames are usually the WeChat username (for example
    ``icetianshan.jpg``).  The bytes are already content-addressed by
    ``import_media``; this projection only adds the profile association.
    """
    media_by_stem: dict[str, str] = {}
    for row in db.execute(
        text("SELECT id, object_path, source_record_id FROM media_assets")
    ).mappings():
        source_name = str(row["source_record_id"] or row["object_path"] or "")
        stem = Path(source_name).stem.strip().lower()
        if stem:
            media_by_stem.setdefault(stem, str(row["id"]))
    linked = 0
    profiles = db.execute(text("""
        SELECT i.profile_id, i.external_id, i.username
        FROM identities i JOIN profiles p ON p.id=i.profile_id
        WHERE i.provider IN ('wechat','wechat_group') AND i.status NOT IN ('invalid','merged')
          AND p.archived_at IS NULL AND p.avatar_media_id IS NULL
    """)).mappings()
    seen_profiles: set[str] = set()
    for row in profiles:
        profile_id = str(row["profile_id"])
        if profile_id in seen_profiles:
            continue
        candidates = [str(row["external_id"] or ""), str(row["username"] or "")]
        # The Chatlog contact's stable wxid is often retained in Monica's
        # custom fields while the visible identity uses an alias.  Include
        # every scalar from the current field value so an existing avatar is
        # attached to the canonical merged profile as well.

        media_id = next(
            (
                media_by_stem.get(candidate.removeprefix("username:").strip().lower())
                for candidate in candidates
                if candidate
                and media_by_stem.get(candidate.removeprefix("username:").strip().lower())
            ),
            None,
        )
        if media_id:
            db.execute(
                text("UPDATE profiles SET avatar_media_id = :media_id WHERE id = :profile_id"),
                {"media_id": media_id, "profile_id": profile_id},
            )
            seen_profiles.add(profile_id)
            linked += 1
    db.commit()
    return linked


def _scalar_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(_scalar_strings(item))
        return result
    if isinstance(value, dict):
        result: list[str] = []
        for item in value.values():
            result.extend(_scalar_strings(item))
        return result
    return []


def link_profile_covers(db: Session, root: Path) -> int:
    """Link Monica's exported WeChat Moments cover files to profiles."""
    manifest_path = find_file(root, "manifest.json")
    if not manifest_path or manifest_path.parent.name != "covers":
        covers_dir = find_directory(root, "covers")
        manifest_path = covers_dir / "manifest.json" if covers_dir else None
    if not manifest_path or not manifest_path.is_file():
        return 0
    manifest = json_load(manifest_path)
    if not isinstance(manifest, dict):
        return 0
    media_by_name = {
        Path(str(row["source_record_id"] or row["object_path"] or "")).name: str(row["id"])
        for row in db.execute(text("SELECT id, object_path, source_record_id FROM media_assets")).mappings()
    }
    profiles_by_key = defaultdict(set)
    for row in db.execute(text("""
        SELECT i.profile_id, i.external_id FROM identities i
        JOIN profiles p ON p.id=i.profile_id AND p.archived_at IS NULL
        WHERE i.provider='wechat' AND i.status NOT IN ('invalid','merged')
    """)).mappings():
        profiles_by_key[str(row["external_id"])].add(str(row["profile_id"]))
    linked = 0
    for wxid, entry in manifest.items():
        if not isinstance(entry, dict):
            continue
        filename = str(entry.get("file") or "")
        media_id = media_by_name.get(filename)
        if not media_id:
            continue
        for profile_id in profiles_by_key.get(str(wxid), set()):
            result = db.execute(text("""
                INSERT INTO media_links(media_id, entity_type, entity_id, role)
                VALUES (:media_id, 'profile', :profile_id, 'cover') ON CONFLICT DO NOTHING
            """), {"media_id": media_id, "profile_id": profile_id})
            linked += result.rowcount
    db.commit()
    return linked


def materialize_remote_media(db: Session, media_root: Path, *, providers=None) -> int:
    """Backfill queue entries; worker downloads without blocking requests/imports."""
    queued = 0
    for row in db.execute(text("""
        SELECT p.id, co.payload_json FROM social_posts p
        JOIN content_objects co ON co.id = p.content_object_id WHERE p.provider = ANY(:providers)
    """),{'providers':providers or ['linkedin']}).mappings():
        payload = row["payload_json"] or {}
        for index, media in enumerate(payload.get("media") or _linkedin_media(payload)):
            queued += enqueue_media(db, url=media.get("source_url"), entity_type="social_post",
                                    entity_id=row["id"], role=media.get("role") or f"media-{index + 1}")
    for row in db.execute(text("""
        SELECT c.profile_id, co.payload_json AS url FROM profile_field_current c
        JOIN profile_field_revisions r ON r.id = c.current_revision_id
        JOIN content_objects co ON co.id = r.content_object_id
        WHERE c.field_key = 'linkedin.avatar_url'
    """)).mappings():
        queued += enqueue_media(db, url=row["url"], entity_type="profile",
                                entity_id=row["profile_id"], role="linkedin_avatar")
    db.commit()
    return queued


def coverage(db: Session, *, source_counts: dict[str, Any]) -> None:
    for key, value in source_counts.items():
        db.execute(
            text("""
          INSERT INTO global_metric_snapshots(metric_key, value_json, source_watermark, freshness_state)
          VALUES (:key, CAST(:value AS jsonb), :watermark, :state)
        """),
            {
                "key": key,
                "value": json.dumps(value, ensure_ascii=False),
                "watermark": now().isoformat(),
                "state": "fresh" if value.get("status") == "complete" else "partial",
            },
        )
    db.commit()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--media-root", type=Path, default=Path("/data/media"))
    parser.add_argument("--skip-moments-posts", action="store_true")
    parser.add_argument("--moments-limit", type=int, default=None)
    parser.add_argument(
        "--download-remote-media",
        action="store_true",
        help="materialize URL-only LinkedIn media into NAS content-addressed storage",
    )
    args = parser.parse_args()
    args.source_root = args.source_root.resolve()
    args.media_root = args.media_root.resolve()
    migrate()
    args.media_root.mkdir(parents=True, exist_ok=True)
    db = SessionLocal()
    try:
        monica_map = load_monica(db, args.source_root)
        wechat_map, _group_map = load_wechat(db, args.source_root, monica_map)
        load_instagram(db, args.source_root, monica_map)
        load_linkedin(db, args.source_root, monica_map)
        load_moments_and_relationships(db, args.source_root, wechat_map)
        load_wechat_interactions(db, args.source_root, wechat_map)
        moments_posts = (
            0
            if args.skip_moments_posts
            else load_moments_posts(db, args.source_root, wechat_map, args.moments_limit)
        )
        media_count = import_media(db, args.source_root, args.media_root)
        linked_media_count = link_profile_media(db)
        linked_cover_count = link_profile_covers(db, args.source_root)
        remote_media_count = (
            materialize_remote_media(db, args.media_root) if args.download_remote_media else 0
        )
        profile_count = db.execute(text("SELECT count(*) FROM profiles")).scalar_one()
        group_count = db.execute(
            text("SELECT count(*) FROM profiles WHERE profile_type='group'")
        ).scalar_one()
        coverage(
            db,
            source_counts={
                "coverage.monica": {"contacts": len(monica_map), "status": "pending_reconciliation"},
                "coverage.wechat": {
                    "profiles": len(wechat_map),
                    "groups": group_count,
                    "moments_posts": moments_posts,
                    "raw_sqlite": True,
                    "message_bodies": "raw_archive_available",
                    "status": "partial",
                },
                "coverage.media": {"deduplicated_assets": media_count, "status": "pending_reconciliation"},
                "coverage.total": {
                    "profiles": profile_count,
                    "groups": group_count,
                    "status": "complete",
                },
            },
        )
        # Refresh all imported profiles once.  Subsequent incremental batches
        # only enqueue their affected IDs through the normal API path.
        db.execute(
            text("""
          INSERT INTO jobs(job_type, payload)
          VALUES ('metrics.refresh', CAST(:payload AS jsonb))
        """),
            {
                "payload": json.dumps(
                    {
                        "batch_id": "full-migration",
                        "source": "full-migration",
                        "affected_profiles": [],
                        "metric_keys": ["global.profile_count", "global.timeline_count"],
                    }
                )
            },
        )
        db.commit()
        print(
            json.dumps(
                {
                    "status": "complete",
                    "monica_profiles": len(monica_map),
                    "wechat_profiles": len(wechat_map),
                    "profiles": profile_count,
                    "groups": group_count,
                    "moments_posts": moments_posts,
                    "media_assets": media_count,
                    "profiles_with_avatars": linked_media_count,
                    "profile_covers": linked_cover_count,
                    "remote_media": remote_media_count,
                },
                ensure_ascii=False,
            )
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
