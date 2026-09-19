"""Authenticated, idempotent import batch projection."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from .config import get_settings
from .content import canonical_json, get_or_create_content
from .remote_media import enqueue_media
from .repositories import add_observation, append_field_revision
from .schemas import ImportBatchRequest


def digest_record(record: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(record)).hexdigest()


def _record_entity(record, request: ImportBatchRequest, content: Any) -> str | None:
    """Resolve the normalized entity type without requiring provider-specific schemas."""
    if record.entity_type:
        return record.entity_type
    if isinstance(content, dict) and content.get("entity_type"):
        return str(content["entity_type"])
    if request.stream in {"posts", "moments"}:
        return "post"
    if request.stream == "stories":
        return "story"
    return None


def _content_value(content: Any) -> Any:
    return content if isinstance(content, dict) else {"value": content}


def _parse_datetime(value: Any) -> Any:
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, UTC)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        value = value.strip()
        if value.isdigit() or (value.startswith("-") and value[1:].isdigit()):
            try:
                return datetime.fromtimestamp(int(value), UTC)
            except (OverflowError, OSError, ValueError):
                return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return value


def _write_raw_manifest(request: ImportBatchRequest) -> tuple[dict[str, Any], str]:
    manifest = request.model_dump(mode="json")
    root = get_settings().raw_root
    for record in manifest["records"]:
        payload = canonical_json(record.pop("content"))
        content_digest = hashlib.sha256(payload).hexdigest()
        relative = f"objects/sha256/{content_digest[:2]}/{content_digest}.json"
        content_path = root / relative
        content_path.parent.mkdir(parents=True, exist_ok=True)
        if not content_path.exists():
            content_path.write_bytes(payload)
        record["content_ref"] = relative
    manifest["manifest_version"] = 2
    digest = digest_record(manifest)
    safe_stream = "".join(
        char if char.isalnum() or char in "-_" else "_" for char in request.stream
    )
    target = get_settings().raw_root / request.source / safe_stream / "sha256" / f"{digest}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        temporary.replace(target)
    return manifest, str(target)


def hydrate_manifest(manifest: dict) -> dict:
    """Read content references, retaining compatibility with inline archives."""
    result = {**manifest, "records": []}
    for record in manifest.get("records", []):
        item = dict(record)
        reference = item.pop("content_ref", None)
        if reference:
            root = get_settings().raw_root.resolve()
            path = (root / reference).resolve()
            if not path.is_relative_to(root / "objects"):
                raise ValueError("Invalid content reference")
            item["content"] = json.loads(path.read_text())
        result["records"].append(item)
    return result


def _ensure_profile_for_record(db: Session, record, request: ImportBatchRequest, content: Any):
    """Create the first local profile projection for a source-native contact.

    Matching an existing person remains an explicit human decision. This helper
    only creates a source-scoped pending profile when a record has no confirmed
    profile ID, so an import can be replayed without losing the original
    identity or conflating two people.
    """
    if getattr(record,'source_is_authoritative',False):return record.profile_id
    if record.profile_id:
        return record.profile_id
    if request.stream not in {"contacts", "profiles", "groups", "people", "legacy"}:
        return None
    normalized = _content_value(content)
    external_id = record.external_id
    provider = "wechat_group" if request.source == "wechat" and request.stream == "groups" else request.source
    identity = (
        db.execute(
            text("""
              SELECT profile_id FROM identities
              WHERE provider = :provider AND external_id = :external_id AND status NOT IN ('invalid','merged')
            """),
            {"provider": provider, "external_id": external_id},
        )
        .mappings()
        .one_or_none()
    )
    if identity and identity["profile_id"]:
        return identity["profile_id"]
    display_name = str(
        normalized.get("display_name")
        or normalized.get("full_name")
        or normalized.get("nickname")
        or normalized.get("nick")
        or normalized.get("remark")
        or external_id
    )
    profile_type = (
        "group"
        if request.stream == "groups" or normalized.get("profile_type") == "group"
        else "person"
    )
    profile_id = db.execute(
        text("""
          INSERT INTO profiles(profile_type, display_name, summary)
          VALUES (:profile_type, :display_name, :summary) RETURNING id
        """),
        {
            "profile_type": profile_type,
            "display_name": display_name,
            "summary": normalized.get("summary") or normalized.get("headline"),
        },
    ).scalar_one()
    db.execute(
        text("""
          INSERT INTO identities(profile_id, provider, external_id, username, profile_url, display_name, status)
          VALUES (:profile_id, :provider, :external_id, :username, :profile_url, :display_name, 'pending')
          ON CONFLICT(provider, external_id) DO UPDATE SET
            profile_id = COALESCE(identities.profile_id, EXCLUDED.profile_id),
            username = COALESCE(EXCLUDED.username, identities.username),
            profile_url = COALESCE(EXCLUDED.profile_url, identities.profile_url),
            display_name = COALESCE(EXCLUDED.display_name, identities.display_name),
            last_seen_at = now()
        """),
        {
            "profile_id": profile_id,
            "provider": provider,
            "external_id": external_id,
            "username": normalized.get("username")
            or normalized.get("alias")
            or normalized.get("u"),
            "profile_url": normalized.get("profile_url"),
            "display_name": display_name,
        },
    )
    return profile_id


def _project_social_record(db: Session, record, request: ImportBatchRequest, content: Any) -> None:
    entity_type = _record_entity(record, request, content)
    if entity_type not in {"post", "story"}:
        return
    normalized = _content_value(content)
    provider = record.provider or request.source
    content_kind = "post_body" if entity_type == "post" else "story_body"
    content_id, digest = get_or_create_content(db, value=normalized, content_kind=content_kind)
    occurred_at = _parse_datetime(record.occurred_at or normalized.get("occurred_at"))
    if entity_type == "post":
        existing = (
            db.execute(
                text("""
                  SELECT id, current_content_hash FROM social_posts
                  WHERE provider = :provider AND external_id = :external_id
                """),
                {"provider": provider, "external_id": record.external_id},
            )
            .mappings()
            .one_or_none()
        )
        if existing:
            db.execute(
                text("""
                  UPDATE social_posts SET profile_id = COALESCE(:profile_id, profile_id),
                    content_object_id = :content_id, occurred_at = COALESCE(:occurred_at, occurred_at),
                    source_updated_at = COALESCE(:source_updated_at, source_updated_at),
                    last_seen_at = now(), current_content_hash = :digest
                  WHERE id = :id
                """),
                {
                    "profile_id": record.profile_id,
                    "content_id": content_id,
                    "occurred_at": occurred_at,
                    "source_updated_at": record.source_updated_at,
                    "digest": digest,
                    "id": existing["id"],
                },
            )
            post_id = existing["id"]
            if existing["current_content_hash"] != digest:
                db.execute(
                    text("""
                      INSERT INTO social_post_revisions
                        (post_id, content_object_id, content_hash, observed_at, source_record_id)
                      VALUES (:post_id, :content_id, :digest, :observed_at, :source_record_id)

                    """),
                    {
                        "post_id": existing["id"],
                        "content_id": content_id,
                        "digest": digest,
                        "observed_at": request.observed_at,
                        "source_record_id": record.external_id,
                    },
                )
        else:
            post_id = db.execute(
                text("""
              INSERT INTO social_posts
                (profile_id, provider, external_id, content_object_id, occurred_at,
                 source_updated_at, current_content_hash)
              VALUES (:profile_id, :provider, :external_id, :content_id, :occurred_at,
                      :source_updated_at, :digest)
              RETURNING id
            """),
            {
                "profile_id": record.profile_id,
                "provider": provider,
                "external_id": record.external_id,
                "content_id": content_id,
                "occurred_at": occurred_at,
                "source_updated_at": record.source_updated_at,
                "digest": digest,
            },
            ).scalar_one()
            db.execute(
                text("""
              INSERT INTO social_post_revisions
                (post_id, content_object_id, content_hash, observed_at, source_record_id)
              VALUES (:post_id, :content_id, :digest, :observed_at, :source_record_id)

            """),
                {
                    "post_id": post_id,
                    "content_id": content_id,
                    "digest": digest,
                    "observed_at": request.observed_at,
                    "source_record_id": record.external_id,
                },
            )

        from .interactions import project_interactions
        project_interactions(db,[record],provider)
        return

    existing = (
        db.execute(
            text("""
              SELECT id, current_content_hash FROM social_stories
              WHERE provider = :provider AND external_id = :external_id
            """),
            {"provider": provider, "external_id": record.external_id},
        )
        .mappings()
        .one_or_none()
    )
    coverage_status = str(normalized.get("coverage_status", "partial"))
    expires_at = _parse_datetime(normalized.get("expires_at"))
    if existing:
        db.execute(
            text("""
              UPDATE social_stories SET profile_id = COALESCE(:profile_id, profile_id),
                content_object_id = :content_id, occurred_at = COALESCE(:occurred_at, occurred_at),
                expires_at = COALESCE(:expires_at, expires_at), current_content_hash = :digest,
                coverage_status = :coverage_status
              WHERE id = :id
            """),
            {
                "profile_id": record.profile_id,
                "content_id": content_id,
                "occurred_at": occurred_at,
                "expires_at": expires_at,
                "digest": digest,
                "coverage_status": coverage_status,
                "id": existing["id"],
            },
        )
        if existing["current_content_hash"] != digest:
            db.execute(
                text("""
                  INSERT INTO social_story_revisions
                    (story_id, content_object_id, content_hash, observed_at)
                  VALUES (:story_id, :content_id, :digest, :observed_at)

                """),
                {
                    "story_id": existing["id"],
                    "content_id": content_id,
                    "digest": digest,
                    "observed_at": request.observed_at,
                },
            )
        return
    story_id = db.execute(
        text("""
          INSERT INTO social_stories
            (profile_id, provider, external_id, content_object_id, occurred_at,
             expires_at, current_content_hash, coverage_status)
          VALUES (:profile_id, :provider, :external_id, :content_id, :occurred_at,
                  :expires_at, :digest, :coverage_status)
          RETURNING id
        """),
        {
            "profile_id": record.profile_id,
            "provider": provider,
            "external_id": record.external_id,
            "content_id": content_id,
            "occurred_at": occurred_at,
            "expires_at": expires_at,
            "digest": digest,
            "coverage_status": coverage_status,
        },
    ).scalar_one()
    db.execute(
        text("""
          INSERT INTO social_story_revisions
            (story_id, content_object_id, content_hash, observed_at)
          VALUES (:story_id, :content_id, :digest, :observed_at)

        """),
        {
            "story_id": story_id,
            "content_id": content_id,
            "digest": digest,
            "observed_at": request.observed_at,
        },
    )


def _project_message_record(db: Session, record, request: ImportBatchRequest, content: Any) -> None:
    entity_type = _record_entity(record, request, content)
    if entity_type != "message" and request.stream not in {"messages", "chat", "conversations"}:
        return
    normalized = _content_value(content)
    conversation_external_id = record.conversation_external_id or str(
        normalized.get("conversation_external_id") or record.external_id
    )
    conversation_type = record.conversation_type or str(
        normalized.get("conversation_type", "direct")
    )
    if conversation_type not in {"direct", "group"}:
        conversation_type = "direct"
    message_type = record.message_type or str(normalized.get("message_type", "text"))
    occurred_at = _parse_datetime(record.occurred_at or normalized.get("occurred_at"))
    if occurred_at is None:
        raise HTTPException(status_code=422, detail="message records require occurred_at")
    content_id, _ = get_or_create_content(db, value=normalized, content_kind="message")
    conversation_id = db.execute(
        text("""
          INSERT INTO conversations(conversation_type, profile_id, external_id)
          VALUES (:conversation_type, :profile_id, :external_id)
          ON CONFLICT (conversation_type, external_id) DO UPDATE SET
            profile_id = COALESCE(EXCLUDED.profile_id, conversations.profile_id)
          RETURNING id
        """),
        {
            "conversation_type": conversation_type,
            "profile_id": record.profile_id,
            "external_id": conversation_external_id,
        },
    ).scalar_one()
    db.execute(
        text("""
          INSERT INTO message_events
            (conversation_id, sender_profile_id, occurred_at, message_type,
             content_object_id, source_record_id)
          VALUES (:conversation_id, :sender_profile_id, :occurred_at, :message_type,
                  :content_id, :source_record_id)
          ON CONFLICT (conversation_id, source_record_id, occurred_at) DO NOTHING
        """),
        {
            "conversation_id": conversation_id,
            "sender_profile_id": record.sender_profile_id,
            "occurred_at": occurred_at,
            "message_type": message_type,
            "content_id": content_id,
            "source_record_id": record.external_id,
        },
    )


def _structured_values(normalized: dict[str, Any], keys: tuple[str, ...]) -> list[Any]:
    for key in keys:
        if key not in normalized or normalized[key] in (None, "", []):
            continue
        value = normalized[key]
        return value if isinstance(value, list) else [value]
    return []


def _entity_id(db: Session, table: str, name: str | None) -> str | None:
    if not name:
        return None
    normalized_name = " ".join(str(name).strip().lower().split())
    if not normalized_name:
        return None
    return db.execute(
        text(f"""
          INSERT INTO {table}(name, normalized_name)
          VALUES (:name, :normalized_name)
          ON CONFLICT (normalized_name) DO UPDATE SET name = EXCLUDED.name
          RETURNING id
        """),
        {"name": str(name).strip(), "normalized_name": normalized_name},
    ).scalar_one()


def _project_structured_fact(
    db: Session,
    *,
    profile_id: str,
    fact_type: str,
    value: Any,
    source_type: str,
    source_record_id: str,
    observed_at: datetime,
    source_account_id=None,
) -> None:
    table_by_type = {
        "address": "profile_address_revisions",
        "employment": "profile_employment_revisions",
        "education": "profile_education_revisions",
    }
    revision_table = table_by_type[fact_type]
    if isinstance(value, dict):
        stable = value.get("source_key") or value.get("id") or value.get("urn")
        if not stable:
            identity_keys = {"employment": ("company_name", "company", "linkedin_url", "start_date", "from_date"),
                             "education": ("school_name", "school", "linkedin_url", "degree", "start_date", "from_date"),
                             "address": ("label", "type", "address", "city")}[fact_type]
            identity = {k: value[k] for k in identity_keys if value.get(k)}
            stable = digest_record(identity or value)
    else:
        stable = str(value)
    fact_key = f"{source_type}:{source_record_id}:{stable}"

    if source_account_id:
        from .platform_store import observe, platform_engine
        with platform_engine(source_type).begin() as source:
            observe(source,source_account_id,fact_type,fact_key,value,
                    source_event='fact:'+observed_at.isoformat()+':'+source_record_id,observed_at=observed_at)

    content_id, digest = get_or_create_content(
        db, value=value, content_kind=f"structured_{fact_type}"
    )
    current = (
        db.execute(
            text("""
              SELECT current_revision_id, current_content_hash, current_source_type
              FROM profile_structured_current
              WHERE profile_id = :profile_id AND fact_type = :fact_type AND fact_key = :fact_key
            """),
            {"profile_id": profile_id, "fact_type": fact_type, "fact_key": fact_key},
        )
        .mappings()
        .one_or_none()
    )
    latest_provider_hash = db.execute(
        text(f"""
          SELECT content_hash FROM {revision_table}
          WHERE source_type = :source_type AND fact_key = :fact_key AND (
            (CAST(:account AS uuid) IS NOT NULL AND source_account_id=:account) OR
            (CAST(:account AS uuid) IS NULL AND profile_id=:profile_id))
          ORDER BY revision_seq DESC LIMIT 1
        """),
        {"profile_id": profile_id, "source_type": source_type, "fact_key": fact_key,"account":source_account_id},
    ).scalar_one_or_none()
    if current and current["current_content_hash"] == digest:
        return
    if source_type != "manual" and latest_provider_hash == digest:
        return
    previous_revision_id = current["current_revision_id"] if current else None
    is_conflict = bool(
        current and current["current_source_type"] == "manual" and source_type != "manual"
    )
    revision_params: dict[str, Any] = {
        "profile_id": profile_id,
        "fact_key": fact_key,
        "content_id": content_id,
        "digest": digest,
        "source_type": source_type,
        "source_record_id": source_record_id,
        "observed_at": observed_at,
        "previous_revision_id": previous_revision_id,
        "is_conflict": is_conflict,
    }
    if fact_type == "address":
        revision_id = db.execute(
            text("""
              INSERT INTO profile_address_revisions
                (profile_id, fact_key, content_object_id, content_hash, source_type, source_record_id,
                 observed_at, previous_revision_id, is_conflict)
              VALUES (:profile_id, :fact_key, :content_id, :digest, :source_type, :source_record_id,
                      :observed_at, :previous_revision_id, :is_conflict)
              RETURNING id
            """),
            revision_params,
        ).scalar_one()
    else:
        entity_table = "companies" if fact_type == "employment" else "schools"
        name_keys = (
            ("company", "company_name", "employer", "name")
            if fact_type == "employment"
            else (
                "school",
                "school_name",
                "institution",
                "name",
            )
        )
        entity_name = (
            value
            if isinstance(value, str)
            else next(
                (value.get(key) for key in name_keys if isinstance(value, dict) and value.get(key)),
                None,
            )
        )
        revision_params["entity_id"] = _entity_id(db, entity_table, entity_name)
        revision_id = db.execute(
            text(f"""
              INSERT INTO {revision_table}
                (profile_id, fact_key, {"company_id" if fact_type == "employment" else "school_id"},
                 content_object_id, content_hash, source_type, source_record_id,
                 observed_at, previous_revision_id, is_conflict)
              VALUES (:profile_id, :fact_key, :entity_id, :content_id, :digest, :source_type,
                      :source_record_id, :observed_at, :previous_revision_id, :is_conflict)
              RETURNING id
            """),
            revision_params,
        ).scalar_one()
    should_project = (
        not current or source_type == "manual" or current["current_source_type"] != "manual"
    )
    if source_account_id:
        db.execute(text(f'UPDATE {revision_table} SET source_account_id=:account WHERE id=:id'),{'account':source_account_id,'id':revision_id})
        db.execute(text('''INSERT INTO source_account_facts(account_id,fact_type,fact_key,revision_id) VALUES(:account,:type,:key,:id)
            ON CONFLICT(account_id,fact_type,fact_key) DO UPDATE SET revision_id=EXCLUDED.revision_id'''),
            {'account':source_account_id,'type':fact_type,'key':fact_key,'id':revision_id})
    if should_project and profile_id:
        db.execute(
            text("""
              INSERT INTO profile_structured_current
                (profile_id, fact_type, fact_key, current_revision_id, current_content_hash,
                 current_source_type, updated_at)
              VALUES (:profile_id, :fact_type, :fact_key, :revision_id, :digest, :source_type, :updated_at)
              ON CONFLICT (profile_id, fact_type, fact_key) DO UPDATE SET
                current_revision_id = EXCLUDED.current_revision_id,
                current_content_hash = EXCLUDED.current_content_hash,
                current_source_type = EXCLUDED.current_source_type,
                updated_at = EXCLUDED.updated_at
            """),
            {
                "profile_id": profile_id,
                "fact_type": fact_type,
                "fact_key": fact_key,
                "revision_id": revision_id,
                "digest": digest,
                "source_type": source_type,
                "updated_at": observed_at,
            },
        )


def _project_structured_profile(
    db: Session, record, request: ImportBatchRequest, content: Any
) -> None:
    if (
        (not record.profile_id and not getattr(record,'source_account_id',None))
        or request.stream not in {"contacts", "profiles", "people", "legacy"}
        or not isinstance(content, dict)
    ):
        return
    normalized = _content_value(content)
    source_type = request.source
    for value in _structured_values(normalized, ("address", "location", "locations", "addresses")):
        _project_structured_fact(
            db,
            profile_id=record.profile_id,
            fact_type="address",
            value=value,
            source_type=source_type,
            source_record_id=record.external_id,
            observed_at=request.observed_at,
            source_account_id=getattr(record,"source_account_id",None),
        )
    for value in _structured_values(
        normalized, ("employment", "experience", "experiences", "work_history", "work")
    ):
        _project_structured_fact(
            db,
            profile_id=record.profile_id,
            fact_type="employment",
            value=value,
            source_type=source_type,
            source_record_id=record.external_id,
            observed_at=request.observed_at,
            source_account_id=getattr(record,"source_account_id",None),
        )
    for value in _structured_values(
        normalized, ("education", "educations", "education_history", "schools")
    ):
        _project_structured_fact(
            db,
            profile_id=record.profile_id,
            fact_type="education",
            value=value,
            source_type=source_type,
            source_record_id=record.external_id,
            observed_at=request.observed_at,
            source_account_id=getattr(record,"source_account_id",None),
        )


def project_batch(db: Session, request: ImportBatchRequest) -> dict[str, Any]:
    db.info.pop('source_lookup',None)
    existing = (
        db.execute(
            text("SELECT * FROM import_batches WHERE idempotency_key = :key"),
            {"key": request.idempotency_key},
        )
        .mappings()
        .one_or_none()
    )
    if existing and existing["status"] == "complete":
        db.execute(
            text("""
              INSERT INTO source_cursors(source, stream, cursor_value, batch_id)
              VALUES (:source, :stream, :cursor_value, :batch_id)
              ON CONFLICT (source, stream) DO UPDATE SET
                cursor_value = EXCLUDED.cursor_value,
                batch_id = EXCLUDED.batch_id,
                updated_at = now()
            """),
            {
                "source": existing["source"],
                "stream": existing["stream"],
                "cursor_value": existing["cursor_after"],
                "batch_id": existing["id"],
            },
        )
        return dict(existing)
    if existing:
        batch_db_id = existing["id"]
    else:
        manifest, manifest_path = _write_raw_manifest(request)
        raw_manifest_id, _ = get_or_create_content(
            db,
            value=manifest,
            content_kind="raw_json",
            storage_uri=manifest_path,
            store_payload=False,
        )
        batch_db_id = db.execute(
            text("""
              INSERT INTO import_batches
                (source, stream, schema_version, batch_id, idempotency_key,
                 cursor_before, cursor_after, raw_manifest_object_id, status)
              VALUES (:source, :stream, :schema_version, :batch_id, :key,
                      :before, :after, :raw_manifest_id, 'projecting')
              RETURNING id
            """),
            {
                "source": request.source,
                "stream": request.stream,
                "schema_version": request.schema_version,
                "batch_id": request.batch_id,
                "key": request.idempotency_key,
                "before": request.cursor_before,
                "after": request.cursor_after,
                "raw_manifest_id": raw_manifest_id,
            },
        ).scalar_one()

    inserted = changed = unchanged = 0
    affected_profiles: set[str] = set()
    from .source_projection import finish_record, prepare_records
    for record in prepare_records(db,request):
        content = record.content
        resolved_profile_id = _ensure_profile_for_record(db, record, request, content)
        if resolved_profile_id and resolved_profile_id != record.profile_id:
            record = record.model_copy(update={"profile_id": resolved_profile_id})
        if record.profile_id:
            affected_profiles.add(str(record.profile_id))
        digest = digest_record(content)
        previous = db.execute(
            text("""
                SELECT content_hash FROM source_observations
                WHERE source = :source AND stream = :stream AND external_id = :external_id
                ORDER BY observed_at DESC LIMIT 1
            """),
            {"source": request.source, "stream": request.stream, "external_id": record.external_id},
        ).scalar_one_or_none()
        state = "new" if previous is None else ("unchanged" if previous == digest else "changed")
        if state == "new":
            inserted += 1
        elif state == "changed":
            changed += 1
        else:
            unchanged += 1
        add_observation(
            db,
            batch_db_id=batch_db_id,
            source=request.source,
            stream=request.stream,
            external_id=record.external_id,
            source_cursor=request.cursor_after,
            digest=digest,
            state=state,
            observed_at=request.observed_at,
            source_updated_at=record.source_updated_at,
        )
        _project_social_record(db, record, request, content)
        _project_message_record(db, record, request, content)
        _project_structured_profile(db, record, request, content)
        # Generic profile streams can project one field or a field map without
        # coupling the importer to provider-specific schemas.
        field_values: dict[str, Any] = {}
        if isinstance(content, dict) and content.get("field_key"):
            field_values[str(content["field_key"])] = content.get("value")
        elif isinstance(content, dict) and isinstance(content.get("fields"), dict):
            field_values = {str(key): value for key, value in content["fields"].items()}
        for field_key, field_value in field_values.items():
            if not record.profile_id and not getattr(record,'source_account_id',None):
                continue
            is_manual_current = (
                db.execute(
                    text("""
                    SELECT current_source_type FROM profile_field_current
                    WHERE profile_id = :profile_id AND field_key = :field_key
                """),
                    {"profile_id": record.profile_id, "field_key": field_key},
                ).scalar_one_or_none()
                == "manual"
            )
            append_field_revision(
                db,
                profile_id=record.profile_id,
                field_key=field_key,
                value=field_value,
                source_type=request.source,
                operation="import",
                source_record_id=record.external_id,
                observed_at=request.observed_at,
                is_conflict=is_manual_current,
                source_account_id=getattr(record,'source_account_id',None),
            )

        finish_record(db,record,request)

        if request.source in ("linkedin", "instagram") and isinstance(content, dict):
            fields = content.get("fields") or {}
            avatar = fields.get(f"{request.source}.avatar_url") or fields.get('instagram.profile_pic_url') or content.get("avatar_url")
            source_account=getattr(record,'source_account_id',None)
            if avatar and (record.profile_id or source_account):
                enqueue_media(db, url=avatar, entity_type="source_account" if source_account else "profile",
                              entity_id=source_account or record.profile_id, role=f"{request.source}_avatar")
            if _record_entity(record, request, content) == "post":
                post_id = db.execute(text("""
                    SELECT id FROM social_posts WHERE provider = :source AND external_id = :id
                """), {"id": record.external_id,'source':request.source}).scalar_one_or_none()
                media_rows = record.media or content.get("media") or [
                    {"source_url": url} for url in content.get("image_urls", [])
                ]
                if post_id:
                    for index, media in enumerate(media_rows):
                        if isinstance(media, dict):
                            enqueue_media(db, url=media.get("source_url") or media.get("url"),
                                          entity_type="social_post", entity_id=post_id,
                                          role=media.get("role") or f"media-{index + 1}")

        for media in record.media:
            media_bytes = media.get("bytes")
            if not isinstance(media_bytes, str):
                # Importers normally upload media separately. A manifest-only record
                # is kept in raw JSON and does not create a fake asset.
                continue
            try:
                payload = bytes.fromhex(media_bytes)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail="media.bytes must be hex") from exc
            media_hash = hashlib.sha256(payload).hexdigest()
            media_content_id, _ = get_or_create_content(
                db, value=payload, content_kind="media", storage_uri=media.get("storage_uri")
            )
            db.execute(
                text("""
                    INSERT INTO media_assets
                      (content_object_id, sha256, media_type, byte_length, object_path,
                       source_type, source_record_id)
                    VALUES (:content_id, :sha256, :media_type, :byte_length, :object_path,
                            :source, :external_id)
                    ON CONFLICT (sha256) DO NOTHING
                """),
                {
                    "content_id": media_content_id,
                    "sha256": media_hash,
                    "media_type": media.get("media_type", "application/octet-stream"),
                    "byte_length": len(payload),
                    "object_path": media.get(
                        "storage_uri", f"sha256/{media_hash[:2]}/{media_hash[2:4]}/{media_hash}"
                    ),
                    "source": request.source,
                    "external_id": record.external_id,
                },
            )

        entity_type = _record_entity(record, request, content)
        if entity_type in {"post", "story"} and record.media:
            provider = record.provider or request.source
            table = "social_posts" if entity_type == "post" else "social_stories"
            entity_name = "social_post" if entity_type == "post" else "social_story"
            entity_id = db.execute(
                text(
                    f"SELECT id FROM {table} WHERE provider = :provider AND external_id = :external_id"
                ),
                {"provider": provider, "external_id": record.external_id},
            ).scalar_one_or_none()
            if entity_id:
                for index, media in enumerate(record.media):
                    media_id = media.get("media_id")
                    if not media_id:
                        media_hash = media.get("sha256")
                        if not media_hash and isinstance(media.get("bytes"), str):
                            try:
                                media_hash = hashlib.sha256(
                                    bytes.fromhex(media["bytes"])
                                ).hexdigest()
                            except ValueError:
                                media_hash = None
                        if media_hash:
                            media_id = db.execute(
                                text("SELECT id FROM media_assets WHERE sha256 = :sha256"),
                                {"sha256": media_hash},
                            ).scalar_one_or_none()
                    if media_id:
                        db.execute(
                            text("""
                              INSERT INTO media_links(media_id, entity_type, entity_id, role)
                              VALUES (:media_id, :entity_type, :entity_id, :role)
                              ON CONFLICT DO NOTHING
                            """),
                            {
                                "media_id": media_id,
                                "entity_type": entity_name,
                                "entity_id": entity_id,
                                "role": media.get("role", f"media-{index + 1}"),
                            },
                        )

    completed_at = datetime.now(UTC)
    if inserted or changed:
        db.execute(
            text("""
              INSERT INTO jobs(job_type, payload)
              VALUES ('metrics.refresh', CAST(:payload AS jsonb))
            """),
            {
                "payload": json.dumps(
                    {
                        "batch_id": request.batch_id,
                        "source": request.source,
                        "affected_profiles": sorted(affected_profiles),
                        "metric_keys": [
                            "global.profile_count",
                            "global.timeline_count",
                            f"provider.{request.source}.coverage",
                        ],
                    }
                )
            },
        )
    result = (
        db.execute(
            text("""
            UPDATE import_batches SET status = 'complete', completed_at = :completed_at,
              inserted_count = :inserted, changed_count = :changed, unchanged_count = :unchanged
            WHERE id = :batch_id
            RETURNING *
        """),
            {
                "completed_at": completed_at,
                "inserted": inserted,
                "changed": changed,
                "unchanged": unchanged,
                "batch_id": batch_db_id,
            },
        )
        .mappings()
        .one()
    )
    db.execute(
        text("""
          INSERT INTO source_cursors(source, stream, cursor_value, batch_id)
          VALUES (:source, :stream, :cursor_value, :batch_id)
          ON CONFLICT (source, stream) DO UPDATE SET
            cursor_value = EXCLUDED.cursor_value,
            batch_id = EXCLUDED.batch_id,
            updated_at = now()
        """),
        {
            "source": request.source,
            "stream": request.stream,
            "cursor_value": request.cursor_after,
            "batch_id": batch_db_id,
        },
    )
    return dict(result)


def list_batches(db: Session, limit: int = 50):
    return list(
        db.execute(
            text("SELECT * FROM import_batches ORDER BY received_at DESC LIMIT :limit"),
            {"limit": limit},
        ).mappings()
    )
