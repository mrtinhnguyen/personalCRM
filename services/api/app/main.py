import base64
import hashlib
import hmac
import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pyotp
from fastapi import (
    Body,
    Depends,
    FastAPI,
    File,
    Header,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from .config import get_settings
from .content import media_object_path
from .db import get_db
from .imports import list_batches, project_batch
from .remote_media import linked_media, merge_media
from .repositories import (
    append_field_revision,
    create_profile,
    get_profile,
    list_field_history,
    list_profiles,
)
from .schemas import (
    ActivityCreate,
    ActivityState,
    BootstrapRequest,
    FieldEdit,
    FieldRevisionOut,
    GroupMembershipCreate,
    IdentityCandidateCreate,
    IdentityCreate,
    IdentityImportCreate,
    ImportBatchOut,
    ImportBatchRequest,
    ImportServiceTokenCreate,
    LoginRequest,
    MediaInitiate,
    ProfileCreate,
    ProfileOut,
    RelationshipCreate,
    SourceAccountLinkUpdate,
    TagCreate,
    TotpCode,
)
from .security import (
    decrypt_secret,
    encrypt_secret,
    hash_password,
    hash_service_token,
    new_csrf_token,
    new_token,
    verify_import_signature,
    verify_password,
)

settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_CSRF_EXEMPT_PATHS = {
    "/api/v1/auth/bootstrap",
    "/api/v1/auth/login",
    "/api/v1/imports/batches",
}


@app.middleware("http")
async def csrf_protection(request: Request, call_next):
    """Protect browser mutations with a double-submit token.

    Import batches are authenticated with their source HMAC and nonce instead
    of a browser session, so that endpoint remains intentionally exempt.
    """
    if request.method not in _SAFE_METHODS and request.url.path not in _CSRF_EXEMPT_PATHS:
        cookie_token = request.cookies.get("crm_csrf")
        header_token = request.headers.get("x-csrf-token")
        if (
            not cookie_token
            or not header_token
            or not hmac.compare_digest(cookie_token, header_token)
        ):
            return JSONResponse(status_code=403, content={"detail": "CSRF token required"})
    return await call_next(request)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _login_attempt_key(email: str, request: Request) -> str:
    ip = request.client.host if request.client else "unknown"
    return hashlib.sha256(f"{email.strip().lower()}|{ip}".encode()).hexdigest()


def _login_is_blocked(db: Session, attempt_key: str) -> bool:
    row = (
        db.execute(
            text("SELECT blocked_until FROM auth_login_attempts WHERE attempt_key = :key"),
            {"key": attempt_key},
        )
        .mappings()
        .one_or_none()
    )
    return bool(row and row["blocked_until"] and row["blocked_until"] > datetime.now(UTC))


def _record_login_failure(db: Session, request: Request, email: str) -> None:
    now = datetime.now(UTC)
    attempt_key = _login_attempt_key(email, request)
    row = (
        db.execute(
            text("""
              SELECT attempts, window_started_at
              FROM auth_login_attempts WHERE attempt_key = :key
            """),
            {"key": attempt_key},
        )
        .mappings()
        .one_or_none()
    )
    if not row or row["window_started_at"] < now - timedelta(minutes=15):
        attempts = 1
        window_started_at = now
    else:
        attempts = int(row["attempts"]) + 1
        window_started_at = row["window_started_at"]
    blocked_until = now + timedelta(minutes=15) if attempts >= 5 else None
    db.execute(
        text("""
          INSERT INTO auth_login_attempts(attempt_key, attempts, window_started_at, blocked_until)
          VALUES (:key, :attempts, :started, :blocked)
          ON CONFLICT (attempt_key) DO UPDATE SET
            attempts = EXCLUDED.attempts,
            window_started_at = EXCLUDED.window_started_at,
            blocked_until = EXCLUDED.blocked_until
        """),
        {
            "key": attempt_key,
            "attempts": attempts,
            "started": window_started_at,
            "blocked": blocked_until,
        },
    )
    db.execute(
        text("""
          INSERT INTO audit_events(action, metadata)
          VALUES ('auth.login.failed', CAST(:metadata AS jsonb))
        """),
        {
            "metadata": json.dumps(
                {"ip": request.client.host if request.client else None, "attempts": attempts}
            )
        },
    )
    db.commit()


def _clear_login_failures(db: Session, request: Request, email: str) -> None:
    db.execute(
        text("DELETE FROM auth_login_attempts WHERE attempt_key = :key"),
        {"key": _login_attempt_key(email, request)},
    )


def current_user(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get("crm_session")
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="login required")
    user = (
        db.execute(
            text("""
            SELECT u.id, u.email FROM sessions s JOIN app_users u ON u.id = s.user_id
            WHERE s.token_hash = :token_hash AND s.revoked_at IS NULL AND s.expires_at > now()
        """),
            {"token_hash": _token_hash(token)},
        )
        .mappings()
        .one_or_none()
    )
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid session")
    return user


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "api"}


@app.get("/api/v1/ready")
def ready(db: Session = Depends(get_db)) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "ready"}


@app.post("/api/v1/auth/bootstrap")
def bootstrap(payload: BootstrapRequest, db: Session = Depends(get_db)):
    existing = db.execute(text("SELECT id FROM app_users LIMIT 1")).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="bootstrap already completed")
    user_id = db.execute(
        text("""
            INSERT INTO app_users(email, password_hash) VALUES (:email, :password_hash) RETURNING id
        """),
        {"email": payload.email, "password_hash": hash_password(payload.password)},
    ).scalar_one()
    db.execute(
        text(
            "INSERT INTO audit_events(user_id, action, metadata) VALUES (:user, 'auth.bootstrap', CAST(:metadata AS jsonb))"
        ),
        {"user": user_id, "metadata": json.dumps({"email": payload.email})},
    )
    db.commit()
    return {"id": str(user_id), "email": payload.email}


@app.get("/api/v1/auth/csrf")
def csrf_token(response: Response):
    token = new_csrf_token()
    response.set_cookie(
        "crm_csrf",
        token,
        httponly=False,
        secure=settings.app_env != "development",
        samesite="lax",
        max_age=settings.session_ttl_seconds,
    )
    return {"csrf_token": token}


@app.post("/api/v1/auth/login")
def login(
    payload: LoginRequest,
    response: Response,
    request: Request,
    db: Session = Depends(get_db),
):
    attempt_key = _login_attempt_key(payload.email, request)
    if _login_is_blocked(db, attempt_key):
        raise HTTPException(status_code=429, detail="too many login attempts; try again later")
    user = (
        db.execute(
            text("SELECT id, password_hash, totp_secret FROM app_users WHERE email = :email"),
            {"email": payload.email},
        )
        .mappings()
        .one_or_none()
    )
    if not user or not verify_password(user["password_hash"], payload.password):
        _record_login_failure(db, request, payload.email)
        raise HTTPException(status_code=401, detail="invalid credentials")
    if user["totp_secret"]:
        try:
            totp_secret = decrypt_secret(user["totp_secret"])
        except Exception as exc:
            raise HTTPException(status_code=401, detail="TOTP configuration invalid") from exc
        verified = bool(payload.totp_code and pyotp.TOTP(totp_secret).verify(payload.totp_code, valid_window=1))
        if not verified and payload.recovery_code:
            recovered=db.execute(text("""UPDATE auth_recovery_codes SET consumed_at=now()
                WHERE user_id=:user AND code_hash=:digest AND consumed_at IS NULL RETURNING code_hash"""),
                {'user':user['id'],'digest':hashlib.sha256(payload.recovery_code.strip().encode()).hexdigest()}).scalar_one_or_none()
            verified=bool(recovered)
        if not verified:
            _record_login_failure(db, request, payload.email)
            raise HTTPException(status_code=401, detail="TOTP code required")
    token = new_token()
    db.execute(
        text("""
          INSERT INTO sessions(user_id, token_hash, expires_at, user_agent, ip_address)
          VALUES (:user_id, :token_hash, now() + (:ttl || ' seconds')::interval, :agent, :ip)
        """),
        {
            "user_id": user["id"],
            "token_hash": _token_hash(token),
            "ttl": settings.session_ttl_seconds,
            "agent": request.headers.get("user-agent"),
            "ip": request.client.host if request.client else None,
        },
    )
    db.execute(
        text("UPDATE app_users SET last_login_at = now() WHERE id = :id"), {"id": user["id"]}
    )
    db.execute(
        text(
            "INSERT INTO audit_events(user_id, action, metadata) VALUES (:user, 'auth.login', CAST(:metadata AS jsonb))"
        ),
        {
            "user": user["id"],
            "metadata": json.dumps({"ip": request.client.host if request.client else None}),
        },
    )
    _clear_login_failures(db, request, payload.email)
    db.commit()
    response.set_cookie(
        "crm_session",
        token,
        httponly=True,
        secure=settings.app_env != "development",
        samesite="lax",
        max_age=settings.session_ttl_seconds,
    )
    return {"status": "authenticated"}


@app.post("/api/v1/auth/totp/setup")
def totp_setup(db: Session = Depends(get_db), user=Depends(current_user)):
    enabled=db.execute(text('SELECT totp_secret IS NOT NULL FROM app_users WHERE id=:id'),{'id':user['id']}).scalar_one()
    if enabled:
        raise HTTPException(status_code=409,detail='TOTP is already enabled')
    secret = pyotp.random_base32()
    db.execute(
        text("UPDATE app_users SET pending_totp_secret = :secret WHERE id = :id"),
        {"secret": encrypt_secret(secret), "id": user["id"]},
    )
    db.commit()
    uri = pyotp.TOTP(secret).provisioning_uri(name=user["email"], issuer_name=settings.app_name)
    return {"secret": secret, "otpauth_url": uri}


@app.post("/api/v1/auth/totp/verify")
def totp_verify(payload: TotpCode, db: Session = Depends(get_db), user=Depends(current_user)):
    encrypted = db.execute(
        text("SELECT pending_totp_secret FROM app_users WHERE id = :id"), {"id": user["id"]}
    ).scalar_one_or_none()
    if not encrypted:
        raise HTTPException(status_code=409, detail="TOTP is not configured")
    if not pyotp.TOTP(decrypt_secret(encrypted)).verify(payload.code, valid_window=1):
        raise HTTPException(status_code=422, detail="invalid TOTP code")
    import secrets
    codes=[secrets.token_hex(8) for _ in range(8)]
    db.execute(text('UPDATE app_users SET totp_secret=pending_totp_secret,pending_totp_secret=NULL WHERE id=:id'),{'id':user['id']})
    for code in codes:
        db.execute(text('INSERT INTO auth_recovery_codes(user_id,code_hash) VALUES(:user,:digest)'),
                   {'user':user['id'],'digest':hashlib.sha256(code.encode()).hexdigest()})
    db.commit()
    return {"status": "verified", "recovery_codes":codes}


@app.get("/api/v1/auth/totp/status")
def totp_status(db: Session=Depends(get_db),user=Depends(current_user)):
    return {'enabled':db.execute(text('SELECT totp_secret IS NOT NULL FROM app_users WHERE id=:id'),{'id':user['id']}).scalar_one()}


@app.post("/api/v1/auth/logout")
def logout(response: Response, request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get("crm_session")
    if token:
        user_id = db.execute(
            text("SELECT user_id FROM sessions WHERE token_hash = :hash"),
            {"hash": _token_hash(token)},
        ).scalar_one_or_none()
        db.execute(
            text("UPDATE sessions SET revoked_at = now() WHERE token_hash = :hash"),
            {"hash": _token_hash(token)},
        )
        if user_id:
            db.execute(
                text("INSERT INTO audit_events(user_id, action) VALUES (:user, 'auth.logout')"),
                {"user": user_id},
            )
        db.commit()
    response.delete_cookie("crm_session")
    return {"status": "logged_out"}


@app.get("/api/v1/me")
def me(user=Depends(current_user)):
    return {"id": str(user["id"]), "email": user["email"]}


@app.get("/api/v1/auth/sessions")
def sessions(request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    current_hash = _token_hash(request.cookies.get("crm_session", ""))
    return list(
        db.execute(
            text("""
              SELECT id, created_at, expires_at, revoked_at, user_agent, ip_address,
                     (token_hash = :current_hash) AS current
              FROM sessions WHERE user_id = :user_id ORDER BY created_at DESC
            """),
            {"user_id": user["id"], "current_hash": current_hash},
        ).mappings()
    )


@app.post("/api/v1/auth/sessions/{session_id}/revoke")
def revoke_session(session_id: UUID, db: Session = Depends(get_db), user=Depends(current_user)):
    revoked = db.execute(
        text("""
          UPDATE sessions SET revoked_at = now()
          WHERE id = :session_id AND user_id = :user_id AND revoked_at IS NULL
          RETURNING id
        """),
        {"session_id": session_id, "user_id": user["id"]},
    ).scalar_one_or_none()
    if not revoked:
        raise HTTPException(status_code=404, detail="session not found")
    db.execute(
        text(
            "INSERT INTO audit_events(user_id, action, entity_type, entity_id) VALUES (:user, 'auth.session.revoked', 'session', :id)"
        ),
        {"user": user["id"], "id": session_id},
    )
    db.commit()
    return {"status": "revoked"}


@app.get("/api/v1/audit/events")
def audit_events(limit: int = 100, db: Session = Depends(get_db), user=Depends(current_user)):
    return list(
        db.execute(
            text("""
              SELECT id, action, entity_type, entity_id, metadata, created_at
              FROM audit_events WHERE user_id = :user_id
              ORDER BY created_at DESC LIMIT :limit
            """),
            {"user_id": user["id"], "limit": min(max(limit, 1), 200)},
        ).mappings()
    )


@app.get("/api/v1/profiles", response_model=list[ProfileOut])
def profiles(
    q: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
    profile_type: str | None = None,
    company: str | None = None,
    school: str | None = None,
    tag: UUID | None = None,
    db: Session = Depends(get_db),
    _user=Depends(current_user),
):
    return list_profiles(db, q, min(max(limit, 1), 100), cursor, profile_type, company, school, tag)


@app.post("/api/v1/profiles", response_model=ProfileOut, status_code=201)
def create_profile_endpoint(
    payload: ProfileCreate, db: Session = Depends(get_db), user=Depends(current_user)
):
    row = create_profile(db, payload.profile_type, payload.display_name, payload.summary)
    db.execute(
        text(
            "INSERT INTO audit_events(user_id, action, entity_type, entity_id) VALUES (:user, 'profile.created', 'profile', :id)"
        ),
        {"user": user["id"], "id": row["id"]},
    )
    db.commit()
    return row


@app.get("/api/v1/profiles/{profile_id}")
def profile(profile_id: UUID, db: Session = Depends(get_db), _user=Depends(current_user)):
    row = get_profile(db, profile_id)
    if not row:
        raise HTTPException(status_code=404, detail="profile not found")
    fields = list(
        db.execute(
            text("""
      SELECT c.field_key, c.current_content_hash, c.current_source_type, c.updated_at,
             co.payload_json AS value
      FROM profile_field_current c
      JOIN profile_field_revisions r ON r.id = c.current_revision_id
      JOIN content_objects co ON co.id = r.content_object_id
      WHERE c.profile_id = :profile_id
        AND c.field_key !~ '(snapshot|raw_payload|direct_stats|group_stats|moments_summary|location_history)$'
      ORDER BY c.field_key
    """),
            {"profile_id": profile_id},
        ).mappings()
    )
    field_values = {str(field["field_key"]): field.get("value") for field in fields}
    avatar_url = next(
        (
            str(field_values[key])
            for key in (
                "wechat.avatar_url",
                "linkedin.avatar_url",
                "instagram.profile_pic_url",
            )
            if field_values.get(key) not in (None, "", [])
        ),
        None,
    )
    cover_media = db.execute(
        text("""
          SELECT m.id, m.source_record_id
          FROM media_links l JOIN media_assets m ON m.id = l.media_id
          WHERE l.entity_type = 'profile' AND l.entity_id = :profile_id AND l.role = 'cover'
          ORDER BY m.created_at DESC LIMIT 1
        """),
        {"profile_id": profile_id},
    ).mappings().one_or_none()
    linkedin_avatar_media_id = db.execute(text("""
        SELECT l.media_id FROM media_links l JOIN media_assets m ON m.id = l.media_id
        WHERE l.entity_type = 'profile' AND l.entity_id = :id AND l.role = 'linkedin_avatar'
        ORDER BY m.created_at DESC LIMIT 1
    """), {"id": profile_id}).scalar_one_or_none()
    platform_avatars=list(db.execute(text("""SELECT DISTINCT ON (l.role,l.source_account_id)
        l.media_id,l.source_account_id,replace(l.role,'_avatar','') AS provider
        FROM media_links l JOIN media_assets m ON m.id=l.media_id
        WHERE l.entity_type='profile' AND l.entity_id=:id
          AND l.role IN ('wechat_avatar','linkedin_avatar','instagram_avatar')
        ORDER BY l.role,l.source_account_id,m.created_at DESC"""),{'id':profile_id}).mappings())
    identities = list(
        db.execute(
            text("""
              SELECT id, provider, external_id, username, profile_url, display_name, status,
                     first_seen_at, last_seen_at
              FROM identities WHERE profile_id = :profile_id AND status NOT IN ('invalid','merged') ORDER BY provider, username NULLS LAST
            """),
            {"profile_id": profile_id},
        ).mappings()
    )
    structured_facts = list(
        db.execute(
            text("""
              SELECT c.fact_type, c.current_content_hash, c.current_source_type, c.updated_at,
                     co.payload_json AS value, companies.name AS company_name,
                     schools.name AS school_name
              FROM profile_structured_current c
              LEFT JOIN profile_address_revisions ar
                ON c.fact_type = 'address' AND ar.id = c.current_revision_id
              LEFT JOIN profile_employment_revisions er
                ON c.fact_type = 'employment' AND er.id = c.current_revision_id
              LEFT JOIN profile_education_revisions ed
                ON c.fact_type = 'education' AND ed.id = c.current_revision_id
              LEFT JOIN content_objects co ON co.id = COALESCE(
                ar.content_object_id, er.content_object_id, ed.content_object_id
              )
              LEFT JOIN companies ON companies.id = er.company_id
              LEFT JOIN schools ON schools.id = ed.school_id
              WHERE c.profile_id = :profile_id ORDER BY c.fact_type
            """),
            {"profile_id": profile_id},
        ).mappings()
    )
    group_members = list(
        db.execute(
            text("""
              SELECT gm.group_profile_id, gm.person_profile_id, gm.role,
                     gm.joined_at, gm.left_at, gm.observed_at, gm.source_record_id,
                     p.display_name, p.profile_type, p.avatar_media_id
              FROM group_memberships gm
              JOIN profiles group_profile ON group_profile.id = gm.group_profile_id
                AND group_profile.profile_type = 'group'
              JOIN profiles p ON p.id = gm.person_profile_id AND p.profile_type = 'person'
              WHERE gm.group_profile_id = :profile_id
                AND gm.person_profile_id <> gm.group_profile_id AND gm.left_at IS NULL
                AND p.archived_at IS NULL
              ORDER BY CASE WHEN gm.role IN ('owner', '群主') THEN 0 ELSE 1 END,
                       p.display_name, p.id LIMIT 16
            """),
            {"profile_id": profile_id},
        ).mappings()
    )
    member_of_groups = list(
        db.execute(
            text("""
              SELECT gm.group_profile_id, gm.person_profile_id, gm.role,
                     gm.joined_at, gm.left_at, gm.observed_at, gm.source_record_id,
                     p.display_name, p.profile_type, p.avatar_media_id
              FROM group_memberships gm
              JOIN profiles p ON p.id = gm.group_profile_id AND p.profile_type = 'group'
              JOIN profiles person_profile ON person_profile.id = gm.person_profile_id
                AND person_profile.profile_type = 'person'
              WHERE gm.person_profile_id = :profile_id
                AND gm.person_profile_id <> gm.group_profile_id AND gm.left_at IS NULL
                AND p.archived_at IS NULL
              ORDER BY p.display_name
            """),
            {"profile_id": profile_id},
        ).mappings()
    )
    group_owners = [member for member in group_members if member['role'] in ('owner', '群主')]
    group_member_count = db.execute(text("""SELECT count(*) FROM group_memberships m
        JOIN profiles p ON p.id=m.person_profile_id AND p.profile_type='person' AND p.archived_at IS NULL
        JOIN profiles g ON g.id=m.group_profile_id AND g.profile_type='group'
        WHERE m.group_profile_id=:id AND m.left_at IS NULL AND m.person_profile_id<>m.group_profile_id"""),{'id':profile_id}).scalar_one()
    tags = list(db.execute(text("""SELECT t.id,t.name,m.source_type FROM tag_memberships m
        JOIN tags t ON t.id=m.tag_id WHERE m.profile_id=:id ORDER BY t.name"""),
        {'id':profile_id}).mappings())
    group_summary = None
    if row['profile_type']=='group':
        stats=db.execute(text("""SELECT o.payload_json FROM profile_field_current c
            JOIN profile_field_revisions r ON r.id=c.current_revision_id JOIN content_objects o ON o.id=r.content_object_id
            WHERE c.profile_id=:id AND c.field_key='wechat.group_stats'"""),{'id':profile_id}).scalar_one_or_none()
        if isinstance(stats,dict):
            from .full_migration import iso
            group_summary={'messages':int(stats.get('n') or 0),'active_senders':int(stats.get('active_senders') or 0),
                           'first':iso(stats.get('first')),'last':iso(stats.get('last'))}
    source_observations = []
    from .profile_presentation import ALIASES, present_identities, presentation
    independent=set(db.execute(text('SELECT provider FROM platform_migration_state WHERE enabled')).scalars())
    if independent:
        # Monica's original mixed notebook is retained in history/imports.
        # Source bios now come exclusively from the linked account projection.
        fields=[dict(field) for field in fields]
        for field in fields:
            if field['field_key']=='monica.custom_fields' and isinstance(field['value'],dict):
                field['value']={label:value for label,value in field['value'].items()
                    if not any((ALIASES.get(label,'').startswith(provider+'.') or label.lower().startswith({'wechat':'微信'}.get(provider,provider)))
                               for provider in independent)}
    return {
        "presentation": presentation(fields, structured_facts),
        "tags": tags,
        "group_summary": group_summary,
        **dict(row),
        "avatar_url": avatar_url,
        "linkedin_avatar_media_id": linkedin_avatar_media_id,
        "platform_avatars": platform_avatars,
        "cover_media_id": str(cover_media["id"]) if cover_media else None,
        "cover_url": (
            str(cover_media["source_record_id"])
            if cover_media and str(cover_media["source_record_id"] or "").startswith("http")
            else None
        ),
        "fields": fields,
        "identities": present_identities(identities),
        "structured_facts": structured_facts,
        "group_members": group_members,
        "group_owners": group_owners,
        "member_of_groups": member_of_groups,
        "group_member_count": group_member_count,
        "linked_group_count": len(member_of_groups),
        "source_observations": source_observations,
    }


@app.post("/api/v1/identities", status_code=201)
def import_identity(
    payload: IdentityImportCreate,
    db: Session = Depends(get_db),
    _user=Depends(current_user),
):
    if payload.profile_id and not get_profile(db, payload.profile_id):
        raise HTTPException(status_code=404, detail="profile not found")
    status_value = "active" if payload.profile_id else "pending"
    row = (
        db.execute(
            text("""
              INSERT INTO identities(profile_id, provider, external_id, username, profile_url, display_name, status)
              VALUES (:profile_id, :provider, :external_id, :username, :profile_url, :display_name, :status)
              ON CONFLICT(provider, external_id) DO UPDATE SET
                profile_id = COALESCE(EXCLUDED.profile_id, identities.profile_id),
                username = EXCLUDED.username,
                profile_url = EXCLUDED.profile_url,
                display_name = EXCLUDED.display_name,
                status = CASE WHEN EXCLUDED.profile_id IS NULL THEN identities.status ELSE 'active' END,
                last_seen_at = now()
              RETURNING id, profile_id, provider, external_id, username, profile_url, display_name, status
            """),
            {**payload.model_dump(), "status": status_value},
        )
        .mappings()
        .one()
    )
    db.commit()
    return dict(row)


@app.patch("/api/v1/profiles/{profile_id}/fields", response_model=FieldRevisionOut)
def edit_field(
    profile_id: UUID, payload: FieldEdit, db: Session = Depends(get_db), user=Depends(current_user)
):
    if not get_profile(db, profile_id):
        raise HTTPException(status_code=404, detail="profile not found")
    if payload.field_key in {'display_name','summary'} and (
        not isinstance(payload.value,str) or (payload.field_key=='display_name' and not payload.value.strip())
    ):
        raise HTTPException(status_code=422,detail='Name and summary must be text, and name cannot be empty')
    revision, _ = append_field_revision(
        db,
        profile_id=profile_id,
        field_key=payload.field_key,
        value=payload.value,
        source_type="manual",
        operation="manual_edit",
        actor_user_id=user["id"],
    )
    db.execute(
        text(
            """
            INSERT INTO audit_events(user_id, action, entity_type, entity_id, metadata)
            VALUES (:user, 'profile.field.edited', 'profile', :id, CAST(:metadata AS jsonb))
            """
        ),
        {
            "user": user["id"],
            "id": profile_id,
            "metadata": json.dumps({"field_key": payload.field_key}),
        },
    )
    db.commit()
    return revision


@app.get("/api/v1/profiles/{profile_id}/history", response_model=list[FieldRevisionOut])
def field_history(
    profile_id: UUID,
    field_key: str | None = None,
    limit: int = 100,
    before: int | None = None,
    db: Session = Depends(get_db),
    _user=Depends(current_user),
):
    return list_field_history(db, profile_id, field_key, limit, before)


@app.get("/api/v1/profiles/{profile_id}/structured-history")
def structured_history(
    profile_id: UUID,
    fact_type: str | None = None,
    db: Session = Depends(get_db),
    _user=Depends(current_user),
):
    if fact_type and fact_type not in {"address", "employment", "education"}:
        raise HTTPException(status_code=422, detail="unsupported structured fact type")
    rows = list(
        db.execute(
            text("""
              SELECT * FROM (
                SELECT ar.id, ar.profile_id, ar.source_account_id, 'address' AS fact_type, ar.content_hash,
                       ar.source_type, ar.source_record_id, ar.observed_at, ar.is_conflict,
                       co.payload_json AS value, NULL::text AS entity_name
                FROM profile_address_revisions ar
                JOIN content_objects co ON co.id = ar.content_object_id
                UNION ALL
                SELECT er.id, er.profile_id, er.source_account_id, 'employment' AS fact_type, er.content_hash,
                       er.source_type, er.source_record_id, er.observed_at, er.is_conflict,
                       co.payload_json AS value, c.name AS entity_name
                FROM profile_employment_revisions er
                JOIN content_objects co ON co.id = er.content_object_id
                LEFT JOIN companies c ON c.id = er.company_id
                UNION ALL
                SELECT ed.id, ed.profile_id, ed.source_account_id, 'education' AS fact_type, ed.content_hash,
                       ed.source_type, ed.source_record_id, ed.observed_at, ed.is_conflict,
                       co.payload_json AS value, s.name AS entity_name
                FROM profile_education_revisions ed
                JOIN content_objects co ON co.id = ed.content_object_id
                LEFT JOIN schools s ON s.id = ed.school_id
              ) facts
              WHERE ((source_account_id IS NULL AND profile_id = :profile_id) OR EXISTS (
                SELECT 1 FROM source_account_links l WHERE l.account_id=facts.source_account_id AND l.profile_id=:profile_id))
                AND (CAST(:fact_type AS text) IS NULL OR fact_type = :fact_type)
              ORDER BY observed_at DESC, id DESC
            """),
            {"profile_id": profile_id, "fact_type": fact_type},
        ).mappings()
    )
    return rows


@app.get("/api/v1/profiles/{profile_id}/metrics")
def profile_metrics(profile_id: UUID, db: Session = Depends(get_db), _user=Depends(current_user)):
    if not get_profile(db, profile_id):
        raise HTTPException(status_code=404, detail="profile not found")
    return list(
        db.execute(
            text("""
              SELECT metric_key, value_json AS value, source_watermark,
                     computed_at, calculation_version, freshness_state
              FROM profile_metrics_current WHERE profile_id = :profile_id
              ORDER BY metric_key
            """),
            {"profile_id": profile_id},
        ).mappings()
    )


def _location_label(location: object) -> str:
    if not isinstance(location, dict):
        return "未命名地点"
    for key in ("name", "poiName", "poi_name", "poi", "address", "city", "province", "country"):
        value = location.get(key)
        if value not in (None, "", "0"):
            return str(value)
    lat = location.get("latitude") or location.get("lat")
    lon = location.get("longitude") or location.get("lon") or location.get("lng")
    return f"{lat}, {lon}" if lat not in (None, "0", 0) and lon not in (None, "0", 0) else "未命名地点"


def _location_point(location: object, coordinate_format: str | None = None) -> tuple[float, float] | None:
    if not isinstance(location, dict):
        return None
    try:
        lat = float(location.get("latitude", location.get("lat")))
        lon = float(location.get("longitude", location.get("lon", location.get("lng"))))
    except (TypeError, ValueError):
        return None
    # Chatlog SNS XML labels its longitude slot "latitude" and its latitude
    # slot "longitude". Both values can fit latitude bounds in Europe/Africa.
    # Reverse only this explicit raw source format, preserving original data.
    if coordinate_format == 'chatlog_sns_xml':
        lat, lon = lon, lat
    if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
        return None
    return lat, lon


def _build_location_summary(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[tuple[str, float, float], dict[str, object]] = {}
    for row in rows:
        location = row.get("location")
        point = _location_point(location, row.get("coordinate_format"))
        if not point:
            continue
        lat, lon = point
        label = _location_label(location)
        key = (label, round(lat, 5), round(lon, 5))
        entry = grouped.setdefault(
            key,
            {
                "label": label,
                "latitude": lat,
                "longitude": lon,
                "count": 0,
                "first_seen": row.get("occurred_at"),
                "last_seen": row.get("occurred_at"),
                "sources": set(),
                "events": [],
            },
        )
        entry["count"] = int(entry["count"]) + int(row.get("count", 1))
        if row.get("source_kind"):
            entry["source_kind"] = row["source_kind"]
        if row.get("occurred_at") and (
            not entry.get("last_seen") or row["occurred_at"] > entry["last_seen"]
        ):
            entry["last_seen"] = row["occurred_at"]
        if row.get("occurred_at") and (
            not entry.get("first_seen") or row["occurred_at"] < entry["first_seen"]
        ):
            entry["first_seen"] = row["occurred_at"]
        if row.get("events"):
            entry["events"].extend(row["events"])
        if row.get("first_seen"):
            entry["first_seen"] = row["first_seen"]
        if row.get("last_seen"):
            entry["last_seen"] = row["last_seen"]
        if row.get('occurred_at'):
            entry['events'].append({'at':row['occurred_at'].isoformat(), 'text':str(row.get('summary') or '')[:120],
                'source':str(row.get('provider') or 'wechat'),
                'url':f"/profiles/{row['profile_id']}?tab=timeline&event={row['id']}" if row.get('id') and row.get('profile_id') else None})
        sources = entry["sources"]
        if isinstance(sources, set):
            sources.add(str(row.get("provider") or "wechat"))
    result = []
    for entry in grouped.values():
        entry["sources"] = sorted(entry["sources"])
        entry["map_url"] = (
            f"https://www.openstreetmap.org/?mlat={entry['latitude']}&mlon={entry['longitude']}#map=14/{entry['latitude']}/{entry['longitude']}"
        )
        result.append(entry)
    return sorted(result, key=lambda item: (-int(item["count"]), str(item["label"])))


@app.get("/api/v1/profiles/{profile_id}/locations")
def profile_locations(profile_id: UUID, db: Session = Depends(get_db), _user=Depends(current_user)):
    owner = get_profile(db, profile_id)
    if not owner:
        raise HTTPException(status_code=404, detail="profile not found")
    if owner['profile_type'] == 'group':
        return {"profile_id": str(profile_id), "total_posts_with_location": 0,
                "place_count": 0, "points": [], "field_sources": []}
    rows = list(
        db.execute(
            text("""
              SELECT p.id,p.profile_id,p.provider,p.occurred_at,l.location,
                left(p.search_body,120) AS summary,l.coordinate_format
              FROM social_posts p JOIN social_post_locations l ON l.post_id=p.id
              WHERE p.profile_id = :profile_id
                AND l.location IS NOT NULL AND l.location<>'null'::jsonb
              ORDER BY p.occurred_at DESC NULLS LAST
              LIMIT 50000
            """),
            {"profile_id": profile_id},
        ).mappings()
    )
    field_rows = list(
        db.execute(
            text("""
              SELECT c.field_key, co.payload_json AS value, c.current_source_type, c.updated_at
              FROM profile_field_current c
              JOIN profile_field_revisions r ON r.id = c.current_revision_id
              JOIN content_objects co ON co.id = r.content_object_id
              WHERE c.profile_id = :profile_id
                AND (c.field_key ILIKE '%address%' OR c.field_key ILIKE '%location%'
                     OR c.field_key = 'wechat.location_history')
              ORDER BY c.updated_at DESC
            """),
            {"profile_id": profile_id},
        ).mappings()
    )
    for field in (field_rows if not any(_location_point(row.get("location"),row.get("coordinate_format")) for row in rows) else []):
        value = field["value"]
        candidates = value if isinstance(value, list) else (value.get("places", [value]) if isinstance(value,dict) else [])
        for candidate in candidates:
            if isinstance(candidate, dict):
                rows.append(
                    {
                        "provider": field["current_source_type"],
                        "occurred_at": None,
                        "location": candidate,
                        "count": int(candidate.get("visits", 0)),
                        "first_seen": candidate.get("first"),
                        "last_seen": candidate.get("last"),
                        "source_kind": "archived_visits" if "visits" in candidate else "profile_address",
                        "events": [{"at": m.get("at"), "text": m.get("text", ""),
                                    "source": field["current_source_type"], "url": None}
                                   for m in candidate.get("moments", []) if m.get("at")],
                    }
                )
    points = _build_location_summary([dict(row) for row in rows])
    return {
        "profile_id": str(profile_id),
        "total_posts_with_location": sum(int(item["count"]) for item in points),
        "place_count": len(points),
        "points": points[:500],
        "field_sources": [
            {"field_key": row["field_key"], "source_type": row["current_source_type"], "updated_at": row["updated_at"]}
            for row in field_rows
        ],
    }


@app.get("/api/v1/metrics/locations")
def location_metrics(provider: str | None=None, year: int | None=None, kind: str='all',
                     db: Session=Depends(get_db), _user=Depends(current_user)):
    if provider not in (None,'wechat','instagram','linkedin') or kind not in ('all','profile','post') or (year is not None and not 1900<=year<=2100):
        raise HTTPException(status_code=422,detail='Invalid location filter')
    from .location_atlas import atlas
    return atlas(db,provider,year,kind)


@app.post(
    "/api/v1/profiles/{profile_id}/history/{revision_id}/restore",
    response_model=FieldRevisionOut,
)
def restore_field_revision(
    profile_id: UUID,
    revision_id: UUID,
    db: Session = Depends(get_db),
    user=Depends(current_user),
):
    source = (
        db.execute(
            text("""
              SELECT r.field_key, co.payload_json
              FROM profile_field_revisions r
              JOIN content_objects co ON co.id = r.content_object_id
              WHERE r.id = :revision_id AND r.profile_id = :profile_id
            """),
            {"revision_id": revision_id, "profile_id": profile_id},
        )
        .mappings()
        .one_or_none()
    )
    if not source or source["payload_json"] is None:
        raise HTTPException(status_code=404, detail="restorable revision not found")
    revision, _ = append_field_revision(
        db,
        profile_id=profile_id,
        field_key=source["field_key"],
        value=source["payload_json"],
        source_type="manual",
        operation="restore",
        actor_user_id=user["id"],
    )
    db.commit()
    return revision


@app.post("/api/v1/profiles/{profile_id}/identities", status_code=201)
def add_identity(
    profile_id: UUID,
    payload: IdentityCreate,
    db: Session = Depends(get_db),
    _user=Depends(current_user),
):
    if not get_profile(db, profile_id):
        raise HTTPException(status_code=404, detail="profile not found")
    existing=db.execute(text('SELECT profile_id,source_account_id FROM identities WHERE provider=:provider AND external_id=:external'),
                        {'provider':payload.provider,'external':payload.external_id}).mappings().one_or_none()
    if existing and existing['profile_id']!=profile_id:
        raise HTTPException(status_code=409,detail='Confirm the source account link through account management')
    if payload.provider in ('wechat','wechat_group','instagram','linkedin'):
        raise HTTPException(status_code=409,detail='Platform accounts are managed through source account links')
    row = (
        db.execute(
            text("""
          INSERT INTO identities(profile_id, provider, external_id, username, profile_url, display_name)
          VALUES (:profile_id, :provider, :external_id, :username, :profile_url, :display_name)
          ON CONFLICT(provider, external_id) DO UPDATE SET
            profile_id = EXCLUDED.profile_id,
            username = EXCLUDED.username,
            profile_url = EXCLUDED.profile_url,
            display_name = EXCLUDED.display_name,
            last_seen_at = now()
          RETURNING id, profile_id, provider, external_id, username, profile_url, display_name, status
        """),
            {"profile_id": profile_id, **payload.model_dump()},
        )
        .mappings()
        .one()
    )
    db.commit()
    return dict(row)




@app.get('/api/v1/source-accounts')
def source_accounts(q: str = '', provider: str | None = None, profile_id: UUID | None = None,
                    cursor: UUID | None = None, db: Session = Depends(get_db), _user=Depends(current_user)):
    return list(db.execute(text('''SELECT a.id,a.provider,a.external_id,a.object_kind,a.display_name,a.username,a.profile_url,
        a.migrated_at IS NOT NULL AS ready,l.profile_id,p.display_name AS linked_profile_name
        FROM source_accounts a LEFT JOIN source_account_links l ON l.account_id=a.id
        LEFT JOIN profiles p ON p.id=l.profile_id
        WHERE (CAST(:provider AS text) IS NULL OR a.provider=:provider)
          AND (CAST(:profile AS uuid) IS NULL OR l.profile_id=:profile)
          AND (CAST(:cursor AS uuid) IS NULL OR a.id>:cursor)
          AND (:q='' OR a.display_name ILIKE :query OR a.external_id ILIKE :query OR a.username ILIKE :query)
          AND NOT EXISTS(SELECT 1 FROM identities i WHERE i.source_account_id=a.id AND i.status='invalid'
            AND NOT EXISTS(SELECT 1 FROM identities v WHERE v.source_account_id=a.id AND v.status NOT IN ('invalid','merged')))
        ORDER BY a.id LIMIT 50'''),{'provider':provider,'profile':profile_id,'cursor':cursor,'q':q,'query':'%'+q+'%'}).mappings())


@app.put('/api/v1/source-accounts/{account_id}/link')
def link_source_account(account_id: UUID,payload: SourceAccountLinkUpdate,db: Session=Depends(get_db),user=Depends(current_user)):
    from .account_links import set_link
    result=set_link(db,account_id,payload.profile_id,expected_profile_id=payload.expected_profile_id,actor=user['id'])
    db.commit()
    return result


@app.get("/api/v1/identity-candidates")
def identity_candidates(
    status_filter: str = "pending",
    db: Session = Depends(get_db),
    _user=Depends(current_user),
):
    return list(
        db.execute(
            text("""
              SELECT c.id, c.score, c.evidence, c.status, i.profile_id AS source_profile_id,
                     i.provider, i.external_id, i.username,
                     p.id AS candidate_profile_id, p.display_name AS candidate_display_name
              FROM identity_candidates c
              JOIN identities i ON i.id = c.identity_id
              JOIN profiles p ON p.id = c.candidate_profile_id
              WHERE c.status = :status
              ORDER BY c.score DESC, c.id LIMIT 100
            """),
            {"status": status_filter},
        ).mappings()
    )


@app.post("/api/v1/identity-candidates", status_code=201)
def create_identity_candidate(
    payload: IdentityCandidateCreate,
    db: Session = Depends(get_db),
    _user=Depends(current_user),
):
    identity_exists = db.execute(
        text("SELECT id FROM identities WHERE id = :id"), {"id": payload.identity_id}
    ).scalar_one_or_none()
    profile_exists = db.execute(
        text("SELECT id FROM profiles WHERE id = :id"), {"id": payload.candidate_profile_id}
    ).scalar_one_or_none()
    if not identity_exists or not profile_exists:
        raise HTTPException(status_code=404, detail="identity or candidate profile not found")
    row = (
        db.execute(
            text("""
              INSERT INTO identity_candidates(identity_id, candidate_profile_id, score, evidence)
              VALUES (:identity_id, :profile_id, :score, CAST(:evidence AS jsonb))
              RETURNING id, identity_id, candidate_profile_id, score, evidence, status
            """),
            {
                "identity_id": payload.identity_id,
                "profile_id": payload.candidate_profile_id,
                "score": payload.score,
                "evidence": json.dumps(payload.evidence, ensure_ascii=False),
            },
        )
        .mappings()
        .one()
    )
    db.commit()
    return dict(row)


@app.post("/api/v1/identity-candidates/{candidate_id}/accept")
def accept_identity_candidate(
    candidate_id: UUID, db: Session = Depends(get_db), user=Depends(current_user)
):
    candidate = (
        db.execute(
            text("""
          SELECT identity_id, candidate_profile_id FROM identity_candidates
          WHERE id = :id AND status = 'pending'
        """),
            {"id": candidate_id},
        )
        .mappings()
        .one_or_none()
    )
    if not candidate:
        raise HTTPException(status_code=404, detail="candidate not found")
    identity = db.execute(text("SELECT profile_id,source_account_id FROM identities WHERE id=:id FOR UPDATE"),
                          {"id": candidate["identity_id"]}).mappings().one()
    original=identity['profile_id']
    target = candidate["candidate_profile_id"]
    if not identity['source_account_id']:
        raise HTTPException(status_code=409,detail='Account migration must finish before linking')
    from .account_links import set_link
    set_link(db,identity['source_account_id'],target,actor=user['id'],expected_profile_id=original,
             evidence={'kind':'accepted-candidate','candidate_id':str(candidate_id)})
    db.execute(
        text("""
          UPDATE identities SET profile_id = :profile_id, status = 'active', last_seen_at = now()
          WHERE id = :identity_id
        """),
        {"profile_id": candidate["candidate_profile_id"], "identity_id": candidate["identity_id"]},
    )
    db.execute(
        text("""
          UPDATE identity_candidates SET status = 'accepted', reviewed_by = :user, reviewed_at = now()
          WHERE id = :id
        """),
        {"id": candidate_id, "user": user["id"]},
    )
    db.commit()
    return {"status": "accepted", "profile_id": str(candidate["candidate_profile_id"])}


@app.post("/api/v1/identity-candidates/{candidate_id}/reject")
def reject_identity_candidate(
    candidate_id: UUID, db: Session = Depends(get_db), user=Depends(current_user)
):
    result = db.execute(
        text("""
          UPDATE identity_candidates SET status = 'rejected', reviewed_by = :user, reviewed_at = now()
          WHERE id = :id AND status = 'pending' RETURNING id
        """),
        {"id": candidate_id, "user": user["id"]},
    ).scalar_one_or_none()
    if not result:
        raise HTTPException(status_code=404, detail="candidate not found")
    db.commit()
    return {"status": "rejected"}


@app.get("/api/v1/profiles/{profile_id}/relationships")
def profile_relationships(
    profile_id: UUID, db: Session = Depends(get_db), _user=Depends(current_user)
):
    rows = list(
        db.execute(
            text("""
              SELECT e.id, e.from_profile_id, e.to_profile_id, rt.name AS relationship_type,
                     source.display_name AS from_display_name,
                     target.display_name AS to_display_name,
                     CASE WHEN e.from_profile_id = :profile_id THEN 'outgoing' ELSE 'incoming' END AS direction,
                     CASE WHEN e.from_profile_id = :profile_id THEN target.id ELSE source.id END AS related_profile_id,
                     CASE WHEN e.from_profile_id = :profile_id THEN target.display_name ELSE source.display_name END AS related_display_name,
                     CASE WHEN e.from_profile_id = :profile_id THEN target.profile_type ELSE source.profile_type END AS related_profile_type,
                     e.note, e.confidence, e.valid_from, e.valid_to, e.source_type
              FROM relationship_edges e
              JOIN relationship_types rt ON rt.id = e.relationship_type_id
              JOIN profiles source ON source.id = e.from_profile_id
              JOIN profiles target ON target.id = e.to_profile_id
              WHERE (e.from_profile_id = :profile_id OR e.to_profile_id = :profile_id)
                AND source.archived_at IS NULL AND target.archived_at IS NULL
                AND source.profile_type='person' AND target.profile_type='person'
                AND e.evidence_kind='relationship'
                AND rt.name NOT IN (
                  'wechat_group', 'wechat_group_member', 'wechat_group_owner',
                  'wechat_group_owned_by', '微信群', '群成员', '群主',
                  '微信名片推荐'
                )
              ORDER BY rt.name, e.created_at DESC
            """),
            {"profile_id": profile_id},
        ).mappings()
    )
    # Group memberships are a first-class relationship in Monica's WeChat
    # model.  Keep them visible in the same API as hand-authored edges so a
    # group Profile has clickable members and a person has clickable groups.
    memberships = list(
        db.execute(
            text("""
              SELECT gm.group_profile_id, gm.person_profile_id, gm.role,
                     groups.display_name AS group_display_name,
                     groups.profile_type AS group_profile_type,
                     people.display_name AS person_display_name,
                     people.profile_type AS person_profile_type,
                     gm.observed_at
              FROM group_memberships gm
              JOIN profiles groups ON groups.id = gm.group_profile_id
                AND groups.profile_type = 'group'
              JOIN profiles people ON people.id = gm.person_profile_id
                AND people.profile_type = 'person'
              WHERE (gm.group_profile_id = :profile_id OR gm.person_profile_id = :profile_id)
                AND gm.group_profile_id <> gm.person_profile_id AND gm.left_at IS NULL
                AND groups.archived_at IS NULL AND people.archived_at IS NULL
              ORDER BY gm.observed_at DESC
            """),
            {"profile_id": profile_id},
        ).mappings()
    )
    for membership in memberships:
        is_group = membership["group_profile_id"] == profile_id
        related_id = membership["person_profile_id"] if is_group else membership["group_profile_id"]
        role = membership["role"] or ("群成员" if is_group else "微信群")
        rows.append(
            {
                "id": f"membership:{membership['group_profile_id']}:{membership['person_profile_id']}",
                "from_profile_id": membership["group_profile_id"],
                "to_profile_id": membership["person_profile_id"],
                "relationship_type": {"owner":"群主", "admin":"管理员", "member":"群成员"}.get(str(role).lower(), role),
                "from_display_name": membership["group_display_name"],
                "to_display_name": membership["person_display_name"],
                "direction": "outgoing" if is_group else "incoming",
                "related_profile_id": related_id,
                "related_display_name": membership["person_display_name"] if is_group else membership["group_display_name"],
                "related_profile_type": membership["person_profile_type"] if is_group else membership["group_profile_type"],
                "note": None,
                "confidence": 1,
                "valid_from": None,
                "valid_to": None,
                "source_type": "wechat",
            }
        )
    return rows


@app.post("/api/v1/profiles/{profile_id}/relationships", status_code=201)
def create_relationship(
    profile_id: UUID,
    payload: RelationshipCreate,
    db: Session = Depends(get_db),
    user=Depends(current_user),
):
    origin=get_profile(db,profile_id); target=get_profile(db,payload.to_profile_id)
    if not origin or not target:
        raise HTTPException(status_code=404, detail="profile not found")
    if profile_id==payload.to_profile_id or origin['profile_type']!='person' or target['profile_type']!='person':
        raise HTTPException(status_code=422,detail='Relationships require two different people; use group membership for groups')
    if any(word in payload.relationship_type.lower() for word in ('group','member','owner','群')):
        raise HTTPException(status_code=422,detail='Use group membership for group roles')
    rel_type = db.execute(
        text("""
          INSERT INTO relationship_types(name) VALUES (:name)
          ON CONFLICT(name) DO UPDATE SET name = EXCLUDED.name RETURNING id
        """),
        {"name": payload.relationship_type},
    ).scalar_one()
    edge = db.execute(
        text("""
          INSERT INTO relationship_edges(from_profile_id, to_profile_id, relationship_type_id, note,
                                         valid_from, valid_to, source_type)
          VALUES (:from_id, :to_id, :type_id, :note, :valid_from, :valid_to, 'manual')
          ON CONFLICT(from_profile_id, to_profile_id, relationship_type_id) DO UPDATE SET
            note = EXCLUDED.note, valid_from = EXCLUDED.valid_from, valid_to = EXCLUDED.valid_to
          RETURNING id
        """),
        {
            "from_id": profile_id,
            "to_id": payload.to_profile_id,
            "type_id": rel_type,
            "note": payload.note,
            "valid_from": payload.valid_from,
            "valid_to": payload.valid_to,
        },
    ).scalar_one()
    db.execute(
        text("""
          INSERT INTO relationship_edge_revisions(edge_id, operation, payload, actor_user_id)
          VALUES (:edge_id, 'created', CAST(:payload AS jsonb), :user)
        """),
        {
            "edge_id": edge,
            "payload": json.dumps(payload.model_dump(), default=str),
            "user": user["id"],
        },
    )
    db.commit()
    return {"id": str(edge), "status": "created"}


@app.post("/api/v1/tags", status_code=201)
def create_tag(payload: TagCreate, db: Session = Depends(get_db), _user=Depends(current_user)):
    row = (
        db.execute(
            text("""
          INSERT INTO tags(name) VALUES (:name)
          ON CONFLICT(name) DO UPDATE SET name = EXCLUDED.name RETURNING id, name
        """),
            {"name": payload.name},
        )
        .mappings()
        .one()
    )
    db.commit()
    return dict(row)


@app.get('/api/v1/tags')
def list_tags(profile_type: str | None=None, db: Session=Depends(get_db), _user=Depends(current_user)):
    if profile_type and profile_type not in ('person','group'):raise HTTPException(status_code=422,detail='Unknown profile type')
    return list(db.execute(text("""SELECT t.id,t.name,count(DISTINCT p.id) AS people,
        array_remove(array_agg(DISTINCT m.source_type) FILTER(WHERE p.id IS NOT NULL),NULL) AS sources
        FROM tags t LEFT JOIN tag_memberships m ON m.tag_id=t.id
        LEFT JOIN profiles p ON p.id=m.profile_id AND p.archived_at IS NULL
            AND (CAST(:kind AS text) IS NULL OR p.profile_type=:kind)
        GROUP BY t.id,t.name ORDER BY t.name,t.id"""),{'kind':profile_type}).mappings())


@app.post("/api/v1/profiles/{profile_id}/tags/{tag_id}")
def attach_tag(
    profile_id: UUID, tag_id: UUID, db: Session = Depends(get_db), user=Depends(current_user)
):
    db.execute(
        text("""
          INSERT INTO tag_memberships(tag_id, profile_id, source_type) VALUES (:tag, :profile, 'manual')
          ON CONFLICT(tag_id, profile_id) DO NOTHING
        """),
        {"tag": tag_id, "profile": profile_id},
    )
    db.execute(
        text("""
          INSERT INTO tag_membership_revisions(tag_id, profile_id, operation, actor_user_id)
          VALUES (:tag, :profile, 'added', :user)
        """),
        {"tag": tag_id, "profile": profile_id, "user": user["id"]},
    )
    db.commit()
    return {"status": "attached"}


@app.post("/api/v1/activities", status_code=201)
def create_activity(
    payload: ActivityCreate,
    db: Session = Depends(get_db),
    user=Depends(current_user),
):
    for participant in payload.participant_profile_ids:
        if not get_profile(db, participant):
            raise HTTPException(status_code=404, detail=f"profile not found: {participant}")
    activity_id = db.execute(
        text("""
          INSERT INTO activities(activity_type, occurred_at, title, body, source_type, created_by, due_at)
          VALUES (:activity_type, :occurred_at, :title, :body, 'manual', :created_by, :due_at)
          RETURNING id
        """),
        {
            "activity_type": payload.activity_type,
            "occurred_at": payload.occurred_at,
            "title": payload.title,
            "body": payload.body,
            "created_by": user["id"],
            "due_at": payload.due_at,
        },
    ).scalar_one()
    for participant in payload.participant_profile_ids:
        db.execute(
            text("""
              INSERT INTO activity_participants(activity_id, profile_id)
              VALUES (:activity_id, :profile_id) ON CONFLICT DO NOTHING
            """),
            {"activity_id": activity_id, "profile_id": participant},
        )
    db.commit()
    return {"id": str(activity_id), "status": "created"}


@app.get("/api/v1/activities")
def list_activities(
    profile_id: UUID | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    _user=Depends(current_user),
):
    params: dict[str, object] = {"limit": min(max(limit, 1), 100), "offset": max(offset, 0)}
    clause = "a.activity_type NOT IN ('wechat_direct_summary','wechat_group_summary')"
    if profile_id:
        params["profile_id"] = profile_id
        clause += " AND EXISTS (SELECT 1 FROM activity_participants ap WHERE ap.activity_id = a.id AND ap.profile_id = :profile_id)"
    return list(
        db.execute(
            text(f"""
              SELECT a.id, a.activity_type, a.occurred_at, a.title, a.body,
                     a.source_type, a.created_at, a.state, a.due_at,
                     (SELECT jsonb_agg(jsonb_build_object('id',p.id,'display_name',p.display_name) ORDER BY p.display_name)
                      FROM activity_participants ap JOIN profiles p ON p.id=ap.profile_id WHERE ap.activity_id=a.id) AS participants
              FROM activities a WHERE {clause}
              ORDER BY a.occurred_at DESC, a.id DESC LIMIT :limit OFFSET :offset
            """),
            params,
        ).mappings()
    )


@app.patch('/api/v1/activities/{activity_id}/state')
def set_activity_state(activity_id: UUID, payload: ActivityState, db: Session = Depends(get_db), _user=Depends(current_user)):
    row=db.execute(text("UPDATE activities SET state=:state WHERE id=:id AND activity_type IN ('task','reminder') RETURNING id,state"),
                   {'id':activity_id,'state':payload.state}).mappings().one_or_none()
    if not row:raise HTTPException(status_code=404,detail='task or reminder not found')
    db.commit();return dict(row)


@app.put('/api/v1/activities/{activity_id}')
def edit_activity(activity_id: UUID, payload: ActivityCreate, db: Session = Depends(get_db), _user=Depends(current_user)):
    # Imported facts keep their source evidence. Manual notes and records can be edited.
    row=db.execute(text("SELECT id FROM activities WHERE id=:id AND source_type='manual' FOR UPDATE"),{'id':activity_id}).first()
    if not row:raise HTTPException(status_code=404,detail='manual record not found')
    for pid in payload.participant_profile_ids:
        if not get_profile(db,pid):raise HTTPException(status_code=404,detail='participant not found')
    db.execute(text("UPDATE activities SET activity_type=:kind,occurred_at=:at,title=:title,body=:body,due_at=:due WHERE id=:id"),
               {'id':activity_id,'kind':payload.activity_type,'at':payload.occurred_at,'title':payload.title,'body':payload.body,'due':payload.due_at})
    db.execute(text('DELETE FROM activity_participants WHERE activity_id=:id'),{'id':activity_id})
    for pid in set(payload.participant_profile_ids):
        db.execute(text('INSERT INTO activity_participants(activity_id,profile_id) VALUES(:id,:pid)'),{'id':activity_id,'pid':pid})
    db.commit();return {'id':str(activity_id),'status':'updated'}


@app.post("/api/v1/groups/{group_id}/members", status_code=201)
def add_group_member(
    group_id: UUID,
    payload: GroupMembershipCreate,
    db: Session = Depends(get_db),
    _user=Depends(current_user),
):
    group = get_profile(db, group_id)
    person = get_profile(db, payload.person_profile_id)
    if not group or group["profile_type"] != "group" or not person or person["profile_type"] != "person":
        raise HTTPException(status_code=422, detail="membership requires a group and a person")
    row = (
        db.execute(
            text("""
              INSERT INTO group_memberships(group_profile_id, person_profile_id, role, joined_at, left_at)
              VALUES (:group_id, :person_id, :role, :joined_at, :left_at)
              ON CONFLICT (group_profile_id, person_profile_id) DO UPDATE SET
                role = EXCLUDED.role, joined_at = EXCLUDED.joined_at, left_at = EXCLUDED.left_at,
                observed_at = now()
              RETURNING group_profile_id, person_profile_id, role, joined_at, left_at, observed_at
            """),
            {
                "group_id": group_id,
                "person_id": payload.person_profile_id,
                "role": payload.role,
                "joined_at": payload.joined_at,
                "left_at": payload.left_at,
            },
        )
        .mappings()
        .one()
    )
    db.commit()
    return dict(row)


@app.get("/api/v1/groups/{group_id}/members")
def group_members(group_id: UUID, limit: int = 50, offset: int = 0, db: Session = Depends(get_db), _user=Depends(current_user)):
    return list(
        db.execute(
            text("""
              SELECT gm.group_profile_id, gm.person_profile_id, p.display_name,
                     gm.role, gm.joined_at, gm.left_at, gm.observed_at,p.profile_type,p.avatar_media_id
              FROM group_memberships gm JOIN profiles p ON p.id = gm.person_profile_id AND p.profile_type='person'
              JOIN profiles g ON g.id=gm.group_profile_id AND g.profile_type='group'
              WHERE gm.group_profile_id = :group_id
                AND gm.person_profile_id <> gm.group_profile_id AND gm.left_at IS NULL AND p.archived_at IS NULL
              ORDER BY CASE WHEN gm.role IN ('owner','群主') THEN 0 ELSE 1 END,p.display_name,p.id LIMIT :limit OFFSET :offset
            """),
            {"group_id": group_id,'limit':min(max(limit,1),100),'offset':max(offset,0)},
        ).mappings()
    )


@app.post("/api/v1/imports/media/initiate", status_code=201)
def initiate_media_upload(
    payload: MediaInitiate,
    db: Session = Depends(get_db),
    user=Depends(current_user),
):
    upload_id = db.execute(
        text("""
          INSERT INTO media_uploads(expected_sha256, media_type, expected_byte_length, temp_path, created_by)
          VALUES (:expected_sha256, :media_type, :expected_byte_length, :temp_path, :created_by)
          RETURNING id
        """),
        {
            "expected_sha256": payload.expected_sha256,
            "media_type": payload.media_type,
            "expected_byte_length": payload.expected_byte_length,
            "temp_path": str(settings.media_root / ".staging" / "pending-upload.part"),
            "created_by": user["id"],
        },
    ).scalar_one()
    temp_path = settings.media_root / ".staging" / f"{upload_id}.part"
    db.execute(
        text("UPDATE media_uploads SET temp_path = :path WHERE id = :id"),
        {"path": str(temp_path), "id": upload_id},
    )
    temp_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path.touch()
    db.commit()
    return {"upload_id": str(upload_id), "next_chunk": 0}


@app.get("/api/v1/imports/media/{upload_id}")
def media_upload_status(
    upload_id: UUID, db: Session = Depends(get_db), _user=Depends(current_user)
):
    row = (
        db.execute(
            text("""
              SELECT id, expected_sha256, media_type, expected_byte_length,
                     next_chunk, received_bytes, status, created_at, completed_at
              FROM media_uploads WHERE id = :id
            """),
            {"id": upload_id},
        )
        .mappings()
        .one_or_none()
    )
    if not row:
        raise HTTPException(status_code=404, detail="upload not found")
    return dict(row)


@app.put("/api/v1/imports/media/{upload_id}/chunks/{chunk}")
def upload_media_chunk(
    upload_id: UUID,
    chunk: int,
    payload: bytes = Body(...),
    db: Session = Depends(get_db),
    _user=Depends(current_user),
):
    row = (
        db.execute(
            text("SELECT temp_path, next_chunk, status FROM media_uploads WHERE id = :id"),
            {"id": upload_id},
        )
        .mappings()
        .one_or_none()
    )
    if not row:
        raise HTTPException(status_code=404, detail="upload not found")
    if row["status"] != "uploading":
        raise HTTPException(status_code=409, detail="upload is not active")
    if chunk != row["next_chunk"]:
        raise HTTPException(status_code=409, detail=f"expected chunk {row['next_chunk']}")
    if not payload:
        raise HTTPException(status_code=422, detail="empty upload chunk")
    with Path(row["temp_path"]).open("ab") as stream:
        stream.write(payload)
    totals = (
        db.execute(
            text("""
          UPDATE media_uploads SET next_chunk = next_chunk + 1,
            received_bytes = received_bytes + :byte_length
          WHERE id = :id
          RETURNING next_chunk, received_bytes
        """),
            {"byte_length": len(payload), "id": upload_id},
        )
        .mappings()
        .one()
    )
    db.commit()
    return {"upload_id": str(upload_id), **dict(totals)}


@app.post("/api/v1/imports/media/{upload_id}/complete", status_code=201)
def complete_media_upload(
    upload_id: UUID, db: Session = Depends(get_db), _user=Depends(current_user)
):
    row = (
        db.execute(
            text("SELECT * FROM media_uploads WHERE id = :id AND status = 'uploading'"),
            {"id": upload_id},
        )
        .mappings()
        .one_or_none()
    )
    if not row:
        raise HTTPException(status_code=404, detail="active upload not found")
    temporary_path = Path(row["temp_path"])
    if not temporary_path.is_file():
        raise HTTPException(status_code=404, detail="upload chunks not found")
    digest = hashlib.sha256()
    byte_length = 0
    with temporary_path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            byte_length += len(chunk)
    sha256 = digest.hexdigest()
    if row["expected_sha256"] and row["expected_sha256"].strip() != sha256:
        raise HTTPException(status_code=422, detail="media sha256 does not match expected value")
    if row["expected_byte_length"] is not None and row["expected_byte_length"] != byte_length:
        raise HTTPException(
            status_code=422, detail="media byte length does not match expected value"
        )
    target = media_object_path(settings.media_root, sha256)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        temporary_path.unlink(missing_ok=True)
    else:
        temporary_path.replace(target)
    content_id = db.execute(
        text("""
          INSERT INTO content_objects(sha256, content_kind, byte_length, storage_uri)
          VALUES (:sha256, 'media', :byte_length, :path)
          ON CONFLICT (content_kind, sha256) DO UPDATE SET storage_uri = EXCLUDED.storage_uri
          RETURNING id
        """),
        {"sha256": sha256, "byte_length": byte_length, "path": str(target)},
    ).scalar_one()
    media_row = (
        db.execute(
            text("""
              INSERT INTO media_assets(content_object_id, sha256, media_type, byte_length, object_path)
              VALUES (:content_id, :sha256, :media_type, :byte_length, :path)
              ON CONFLICT (sha256) DO UPDATE SET object_path = EXCLUDED.object_path
              RETURNING id, sha256, media_type, byte_length, object_path
            """),
            {
                "content_id": content_id,
                "sha256": sha256,
                "media_type": row["media_type"],
                "byte_length": byte_length,
                "path": str(target),
            },
        )
        .mappings()
        .one()
    )
    db.execute(
        text("UPDATE media_uploads SET status = 'complete', completed_at = now() WHERE id = :id"),
        {"id": upload_id},
    )
    db.commit()
    return dict(media_row)


@app.get('/api/v1/profiles/{profile_id}/contact-events/summary')
def contact_event_summary(profile_id: UUID, db: Session=Depends(get_db), _user=Depends(current_user)):
    from .contact_events import summary
    return summary(db,profile_id)


@app.get('/api/v1/profiles/{profile_id}/contact-events')
def contact_event_records(profile_id: UUID, kind: str='call', offset: int=0, limit: int=30,
                          db: Session=Depends(get_db), _user=Depends(current_user)):
    if kind not in ('call','money'):raise HTTPException(status_code=422,detail='Unknown record kind')
    from .contact_events import records
    return records(db,profile_id,kind,offset,limit)


@app.get('/api/v1/profiles/{profile_id}/chat-months')
def profile_chat_months(profile_id: UUID, db: Session = Depends(get_db), _user=Depends(current_user)):
    from .chat_months import profile_months
    return profile_months(db,profile_id)


def message_month_bounds(month, timezone):
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    try:
        zone=ZoneInfo(timezone)
        start=datetime.strptime(month,'%Y-%m').replace(tzinfo=zone)
        if start.strftime('%Y-%m')!=month:raise ValueError()
        end=start.replace(year=start.year+1,month=1) if start.month==12 else start.replace(month=start.month+1)
        return start,end
    except (ValueError,ZoneInfoNotFoundError):
        raise HTTPException(status_code=422,detail='Invalid month or timezone') from None


@app.get("/api/v1/profiles/{profile_id}/messages")
def profile_messages(
    profile_id: UUID | None, before: datetime | None = None, before_id: UUID | None = None,
    conversation_type: str | None = None, q: str | None = None, limit: int = 50,
    conversation_id: UUID | None = None, month: str | None = None, timezone: str = "UTC",
    db: Session = Depends(get_db), _user=Depends(current_user),
):
    clauses=[]
    message_clauses=['s.conversation_id=c.id']
    params={"limit":min(max(limit,1),100)}
    if profile_id:
        clauses.append('c.profile_id=:profile_id');params['profile_id']=profile_id
    if conversation_id:
        clauses.append('c.id=:conversation_id');params['conversation_id']=conversation_id
    if not clauses:raise HTTPException(status_code=422,detail='Select a conversation or profile')
    if month:
        start,end=message_month_bounds(month,timezone)
        message_clauses.extend(["s.occurred_at>=:month_start","s.occurred_at<:month_end"])
        params.update(month_start=start,month_end=end)
    if before:
        message_clauses.append("(s.occurred_at,s.message_id)<(:before,CAST(:before_id AS uuid))")
        params.update(before=before,before_id=before_id or UUID('ffffffff-ffff-ffff-ffff-ffffffffffff'))
    if conversation_type in {'direct','group'}:
        clauses.append('c.conversation_type=:kind');params['kind']=conversation_type
    if q:
        message_clauses.append("s.body ILIKE :q");params['q']='%'+q.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
    return list(db.execute(text(f"""WITH selected AS MATERIALIZED (
        SELECT s.*,c.conversation_type FROM conversations c JOIN LATERAL (
            SELECT s.message_id,s.occurred_at,s.conversation_id,s.body FROM message_search s
            WHERE {' AND '.join(message_clauses)}
            ORDER BY s.occurred_at DESC,s.message_id DESC LIMIT :limit
        ) s ON true WHERE {' AND '.join(clauses)}
        ORDER BY s.occurred_at DESC,s.message_id DESC LIMIT :limit
        )
        SELECT m.id,s.conversation_id,s.conversation_type,
          CASE WHEN m.sender_account_id IS NOT NULL THEN account_link.profile_id ELSE m.sender_profile_id END AS sender_profile_id,
        p.display_name AS sender_name,m.occurred_at,m.message_type,s.body AS text
        FROM selected s JOIN message_events m ON m.id=s.message_id AND m.occurred_at=s.occurred_at
        LEFT JOIN source_account_links account_link ON account_link.account_id=m.sender_account_id
        LEFT JOIN profiles p ON p.id=CASE WHEN m.sender_account_id IS NOT NULL THEN account_link.profile_id ELSE m.sender_profile_id END
        ORDER BY m.occurred_at DESC,m.id DESC"""),params).mappings())


@app.get('/api/v1/conversations')
def list_conversations(q: str = '', cursor: UUID | None = None, limit: int = 40, db: Session = Depends(get_db), _user=Depends(current_user)):
    return list(db.execute(text("""SELECT c.id,c.conversation_type,c.external_id,c.profile_id,p.display_name
        FROM conversations c LEFT JOIN profiles p ON p.id=c.profile_id
        WHERE (p.display_name ILIKE :q OR c.external_id ILIKE :q)
        AND (CAST(:cursor AS uuid) IS NULL OR c.id>CAST(:cursor AS uuid))
        ORDER BY c.id LIMIT :limit"""),{'q':'%'+q+'%','cursor':cursor,'limit':min(max(limit,1),100)}).mappings())


@app.get('/api/v1/conversations/{conversation_id}/messages')
def conversation_messages(conversation_id: UUID, before: datetime | None = None, before_id: UUID | None = None,
                          q: str | None = None, limit: int = 50, month: str | None = None, timezone: str = "UTC", db: Session = Depends(get_db), _user=Depends(current_user)):
    return profile_messages(None,before=before,before_id=before_id,q=q,limit=limit,month=month,timezone=timezone,conversation_id=conversation_id,db=db,_user=_user)


@app.post("/api/v1/media", status_code=201)
async def upload_media(
    file: UploadFile = File(...),
    media_type: str | None = None,
    db: Session = Depends(get_db),
    _user=Depends(current_user),
):
    staging = settings.media_root / ".staging"
    staging.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=staging, delete=False) as temp:
        temporary_path = Path(temp.name)
        digest = hashlib.sha256()
        byte_length = 0
        while chunk := await file.read(1024 * 1024):
            digest.update(chunk)
            byte_length += len(chunk)
            temp.write(chunk)
    sha256 = digest.hexdigest()
    target = media_object_path(settings.media_root, sha256)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        temporary_path.replace(target)
    else:
        temporary_path.unlink(missing_ok=True)
    content_id = db.execute(
        text("""
          INSERT INTO content_objects(sha256, content_kind, byte_length, storage_uri)
          VALUES (:sha256, 'media', :byte_length, :path)
          ON CONFLICT(content_kind, sha256) DO UPDATE SET storage_uri = EXCLUDED.storage_uri
          RETURNING id
        """),
        {"sha256": sha256, "byte_length": byte_length, "path": str(target)},
    ).scalar_one()
    media_row = (
        db.execute(
            text("""
          INSERT INTO media_assets(content_object_id, sha256, media_type, byte_length, object_path)
          VALUES (:content_id, :sha256, :media_type, :byte_length, :path)
          ON CONFLICT(sha256) DO UPDATE SET object_path = EXCLUDED.object_path
          RETURNING id, sha256, media_type, byte_length, object_path
        """),
            {
                "content_id": content_id,
                "sha256": sha256,
                "media_type": media_type or file.content_type or "application/octet-stream",
                "byte_length": byte_length,
                "path": str(target),
            },
        )
        .mappings()
        .one()
    )
    db.commit()
    return dict(media_row)


@app.get("/api/v1/media/{media_id}")
def download_media(media_id: UUID, variant: str | None = None, db: Session = Depends(get_db), _user=Depends(current_user)):
    asset = db.execute(
        text("SELECT object_path, media_type FROM media_assets WHERE id = :id"), {"id": media_id}
    ).mappings().one_or_none()
    path = asset["object_path"] if asset else None
    if not path or not Path(path).is_file():
        raise HTTPException(status_code=404, detail="media not found")
    mime = asset['media_type']
    if variant == 'thumb' and mime.startswith('image/'):
        from PIL import Image, ImageOps, UnidentifiedImageError
        thumbnail = settings.media_root / 'thumbnails' / f'{media_id}.webp'
        if not thumbnail.exists():
            try:
                thumbnail.parent.mkdir(parents=True, exist_ok=True)
                with Image.open(path) as original:
                    if original.width * original.height <= 40_000_000:
                        preview = ImageOps.exif_transpose(original)
                        preview.thumbnail((720, 720))
                        with tempfile.NamedTemporaryFile(dir=thumbnail.parent, suffix='.webp', delete=False) as temporary:
                            temp_path = Path(temporary.name)
                        try:
                            preview.convert('RGB').save(temp_path, 'WEBP', quality=78)
                            temp_path.replace(thumbnail)
                        finally:
                            temp_path.unlink(missing_ok=True)
            except (OSError, UnidentifiedImageError, Image.DecompressionBombError):
                pass
        if thumbnail.exists():
            path = thumbnail
            mime = 'image/webp'
    return FileResponse(path, media_type=mime, headers={"Cache-Control": "private, max-age=86400", "X-Content-Type-Options": "nosniff"})


@app.get("/api/v1/search")
def search(q: str, limit: int = 30, db: Session = Depends(get_db), _user=Depends(current_user)):
    if len(q.strip()) < 2:
        return []
    like = f"%{q.strip()}%"
    rows = list(
        db.execute(
            text("""
              SELECT id, 'profile' AS entity_type, display_name AS title, COALESCE(summary, '') AS summary
              FROM profiles WHERE archived_at IS NULL AND (display_name ILIKE :like OR summary ILIKE :like)
              UNION ALL
              SELECT id, 'tag', name, '' FROM tags WHERE name ILIKE :like
              UNION ALL
              SELECT p.id, 'timeline', p.provider || ' · ' || p.external_id,
                     left(p.search_body,240)
              FROM social_posts p
              WHERE p.provider ILIKE :like
                 OR p.search_body ILIKE :like
              UNION ALL
              SELECT s.id, 'timeline', s.provider || ' · ' || s.external_id,
                     left(s.search_body,240)
              FROM social_stories s
              WHERE s.provider ILIKE :like
                 OR s.search_body ILIKE :like
              UNION ALL
              SELECT a.id, 'activity', a.title, COALESCE(a.body, '')
              FROM activities a WHERE a.activity_type NOT IN ('wechat_direct_summary','wechat_group_summary')
                AND (a.title ILIKE :like OR a.body ILIKE :like)
              ORDER BY title LIMIT :limit
            """),
            {"like": like, "limit": min(max(limit, 1), 100)},
        ).mappings()
    )
    return rows


@app.get("/api/v1/metrics/summary")
def metrics_summary(db: Session = Depends(get_db), _user=Depends(current_user)):
    counts = (
        db.execute(
            text("""
          SELECT
            (SELECT count(*) FROM profiles WHERE profile_type = 'person' AND archived_at IS NULL) AS people,
            (SELECT count(*) FROM profiles WHERE profile_type = 'group' AND archived_at IS NULL) AS groups,
            (SELECT count(*) FROM identities WHERE status = 'active') AS identities,
            (SELECT count(*) FROM identities WHERE provider = 'wechat' AND status = 'active') AS wechat_identities,
            (SELECT count(*) FROM identities WHERE provider = 'instagram' AND status = 'active') AS instagram_identities,
            (SELECT count(*) FROM identities WHERE provider = 'linkedin' AND status = 'active') AS linkedin_identities,
            (SELECT count(*) FROM source_observations WHERE source = 'wechat' AND stream = 'moments') AS wechat_moments,
            (SELECT count(*) FROM group_memberships) AS group_memberships,
            (SELECT count(*) FROM media_assets) AS media,
            (SELECT count(*) FROM social_posts) AS posts,
            (SELECT count(*) FROM social_stories) AS stories,
            (SELECT count(*) FROM relationship_edges) AS relationships,
            (SELECT count(*) FROM activities) AS activities,
            (SELECT count(*) FROM companies) AS companies,
            (SELECT count(*) FROM schools) AS schools,
            (SELECT count(*) FROM profile_address_revisions) AS address_revisions,
            (SELECT count(*) FROM source_observations WHERE state = 'unchanged') AS unchanged_observations,
            (SELECT count(*) FROM profile_field_revisions) AS revisions
        """)
        )
        .mappings()
        .one()
    )
    return dict(counts)


@app.get("/api/v1/relationships")
def relationships(limit: int = 10, db: Session = Depends(get_db), _user=Depends(current_user)):
    """Return a small, name-resolved relationship slice for the dashboard.

    The full graph remains on-demand. This endpoint only reads the indexed edge
    projection and keeps the overview request bounded for large archives.
    """
    return list(
        db.execute(
            text("""
              SELECT e.id, e.from_profile_id, e.to_profile_id,
                     source.display_name AS from_display_name,
                     target.display_name AS to_display_name,
                     rt.name AS relationship_type, e.source_type,
                     e.confidence, e.created_at
              FROM relationship_edges e
              JOIN profiles source ON source.id = e.from_profile_id
              JOIN profiles target ON target.id = e.to_profile_id
              JOIN relationship_types rt ON rt.id = e.relationship_type_id
              ORDER BY e.created_at DESC, e.id DESC
              LIMIT :limit
            """),
            {"limit": min(max(limit, 1), 50)},
        ).mappings()
    )


@app.get("/api/v1/relationships/graph")
def relationship_graph(
    limit: int = 900,
    source_type: str | None = None,
    relationship_type: str | None = None,
    min_confidence: float = 0,
    format: str | None = None,
    focus: UUID | None = None,
    db: Session = Depends(get_db),
    _user=Depends(current_user),
):
    """Return a bounded, name-resolved graph projection for the relationship UI.

    The database remains the source of truth for the full edge set.  The web
    graph only receives the strongest/recent slice requested by the user so a
    16k-edge archive never blocks a normal Profile request.
    """
    if format == "monica":
        from .graph import graph_projection
        return graph_projection(db, settings.raw_root, limit, focus)

    clauses = ["1 = 1"]
    params: dict[str, object] = {"limit": min(max(limit, 50), 5000)}
    if source_type:
        clauses.append("e.source_type = :source_type")
        params["source_type"] = source_type
    if relationship_type:
        clauses.append("rt.name = :relationship_type")
        params["relationship_type"] = relationship_type
    if min_confidence > 0:
        clauses.append("COALESCE(e.confidence, 0) >= :min_confidence")
        params["min_confidence"] = min(min_confidence, 1)
    edges = list(
        db.execute(
            text(f"""
              SELECT e.id, e.from_profile_id, e.to_profile_id,
                     source.display_name AS from_display_name,
                     source.profile_type AS from_profile_type,
                     target.display_name AS to_display_name,
                     target.profile_type AS to_profile_type,
                     rt.name AS relationship_type, e.source_type,
                     e.confidence, e.note, e.created_at
              FROM relationship_edges e
              JOIN profiles source ON source.id = e.from_profile_id
              JOIN profiles target ON target.id = e.to_profile_id
              JOIN relationship_types rt ON rt.id = e.relationship_type_id
              WHERE {" AND ".join(clauses)}
              ORDER BY COALESCE(e.confidence, 0) DESC, e.created_at DESC, e.id DESC
              LIMIT :limit
            """),
            params,
        ).mappings()
    )
    node_map: dict[str, dict[str, object]] = {}
    for edge in edges:
        for prefix in ("from", "to"):
            node_id = str(edge[f"{prefix}_profile_id"])
            node = node_map.setdefault(
                node_id,
                {
                    "id": edge[f"{prefix}_profile_id"],
                    "display_name": edge[f"{prefix}_display_name"],
                    "profile_type": edge[f"{prefix}_profile_type"],
                    "degree": 0,
                },
            )
            node["degree"] = int(node["degree"]) + 1
    total_edges = db.execute(
        text(f"""
          SELECT count(*) FROM relationship_edges e
          JOIN relationship_types rt ON rt.id = e.relationship_type_id
          WHERE {" AND ".join(clauses)}
        """),
        params,
    ).scalar_one()
    total_nodes = db.execute(
        text("SELECT count(*) FROM profiles WHERE archived_at IS NULL")
    ).scalar_one()
    type_counts = list(
        db.execute(
            text("""
              SELECT rt.name AS relationship_type, count(*) AS edge_count
              FROM relationship_edges e JOIN relationship_types rt ON rt.id = e.relationship_type_id
              GROUP BY rt.name ORDER BY edge_count DESC, rt.name
            """)
        ).mappings()
    )
    source_counts = list(
        db.execute(
            text("""
              SELECT source_type, count(*) AS edge_count
              FROM relationship_edges GROUP BY source_type ORDER BY edge_count DESC, source_type
            """)
        ).mappings()
    )
    return {
        "nodes": list(node_map.values()),
        "edges": edges,
        "total_edges": total_edges,
        "total_nodes": total_nodes,
        "visible_edges": len(edges),
        "relationship_types": type_counts,
        "sources": source_counts,
    }


@app.get("/api/v1/metrics/snapshots")
def metric_snapshots(limit: int = 100, db: Session = Depends(get_db), _user=Depends(current_user)):
    return list(
        db.execute(
            text("""
              SELECT DISTINCT ON (metric_key) metric_key, value_json AS value,
                     source_watermark, computed_at, calculation_version, freshness_state
              FROM global_metric_snapshots
              ORDER BY metric_key, computed_at DESC
              LIMIT :limit
            """),
            {"limit": min(max(limit, 1), 200)},
        ).mappings()
    )


@app.get("/api/v1/timeline/summary")
def timeline_summary(profile_id: UUID, db: Session = Depends(get_db), _user=Depends(current_user)):
    if not get_profile(db, profile_id):
        raise HTTPException(status_code=404, detail="profile not found")
    providers: dict[str, dict[str, object]] = {}
    post_rows = list(
        db.execute(
            text("""
              SELECT provider, count(*) AS posts, max(occurred_at) AS latest,
                     COALESCE(sum(COALESCE((co.payload_json->>'like_count')::int, 0)), 0) AS likes,
                     COALESCE(sum(COALESCE((co.payload_json->>'comment_count')::int, 0)), 0) AS comments,
                     COALESCE(sum(jsonb_array_length(COALESCE(co.payload_json->'media', '[]'::jsonb))), 0) AS media
              FROM social_posts p
              LEFT JOIN content_objects co ON co.id = p.content_object_id
              WHERE p.profile_id = :profile_id
              GROUP BY provider
            """),
            {"profile_id": profile_id},
        ).mappings()
    )
    for row in post_rows:
        providers[str(row["provider"])] = {
            "posts": int(row["posts"]),
            "stories": 0,
            "events": int(row["posts"]),
            "media": int(row["media"] or 0),
            "likes": int(row["likes"] or 0),
            "comments": int(row["comments"] or 0),
            "latest": row["latest"],
        }
    story_rows = list(
        db.execute(
            text("""
              SELECT provider, count(*) AS stories, max(occurred_at) AS latest
              FROM social_stories WHERE profile_id = :profile_id GROUP BY provider
            """),
            {"profile_id": profile_id},
        ).mappings()
    )
    for row in story_rows:
        provider = str(row["provider"])
        summary = providers.setdefault(provider, {"posts": 0, "stories": 0, "events": 0, "media": 0, "likes": 0, "comments": 0, "latest": None})
        summary["stories"] = int(row["stories"])
        summary["events"] = int(summary["events"]) + int(row["stories"])
        if not summary.get("latest") or (row["latest"] and row["latest"] > summary["latest"]):
            summary["latest"] = row["latest"]
    manual_count = db.execute(
        text("""
          SELECT count(*) FROM activities a
          JOIN activity_participants ap ON ap.activity_id = a.id
          WHERE ap.profile_id = :profile_id
        """),
        {"profile_id": profile_id},
    ).scalar_one()
    if manual_count:
        latest_manual = db.execute(
            text("""
              SELECT max(a.occurred_at) FROM activities a
              JOIN activity_participants ap ON ap.activity_id = a.id
              WHERE ap.profile_id = :profile_id
            """),
            {"profile_id": profile_id},
        ).scalar_one()
        providers["manual"] = {"posts": 0, "stories": 0, "events": int(manual_count), "media": 0, "likes": 0, "comments": 0, "latest": latest_manual}
    total = sum(int(item["events"]) for item in providers.values())
    return {"profile_id": str(profile_id), "providers": providers, "total_events": total}


@app.get("/api/v1/timeline/{event_id}")
def timeline_detail(
    event_id: UUID,
    provider: str | None = None,
    db: Session = Depends(get_db),
    _user=Depends(current_user),
):
    """Load one timeline event on demand for the Profile timeline drawer."""
    provider_clause = " AND p.provider = :provider" if provider else ""
    params: dict[str, object] = {"id": event_id}
    if provider:
        params["provider"] = provider
    post = (
        db.execute(
            text(f"""
          SELECT p.id, p.provider, p.external_id, p.profile_id,
                 p.occurred_at, p.source_updated_at, p.last_seen_at, p.status,
                 p.current_content_hash AS content_hash,
                 profiles.display_name AS profile_display_name,
                 co.payload_json AS content
          FROM social_posts p
          LEFT JOIN profiles ON profiles.id = p.profile_id
          LEFT JOIN content_objects co ON co.id = p.content_object_id
          WHERE p.id = :id{provider_clause}
        """),
            params,
        )
        .mappings()
        .one_or_none()
    )
    if post:
        revisions = list(
            db.execute(
                text("""
                  SELECT content_hash, observed_at, source_record_id
                  FROM social_post_revisions
                  WHERE post_id = :id ORDER BY observed_at DESC, id DESC
                """),
                {"id": event_id},
            ).mappings()
        )
        media = list(
            db.execute(
                text("""
                  SELECT m.id, m.media_type, m.byte_length, m.width, m.height,
                         m.duration_ms, m.capture_at, COALESCE(r.source_url, m.source_record_id) AS source_url
                  FROM media_links l JOIN media_assets m ON m.id = l.media_id
                  LEFT JOIN remote_media_sources r ON r.media_id = m.id
                  WHERE l.entity_type IN ('social_post', 'post') AND l.entity_id = :id
                  ORDER BY l.role, m.id
                """),
                {"id": event_id},
            ).mappings()
        )
        interactions = list(
            db.execute(
                text("""
                  SELECT i.id, i.interaction_type, i.external_id,
                         i.author_profile_id, i.author_external_id, i.author_name,
                         i.occurred_at, i.metadata, co.payload_json AS content
                  FROM social_interactions i
                  LEFT JOIN content_objects co ON co.id = i.content_object_id
                  WHERE i.post_id = :id
                  ORDER BY i.occurred_at ASC NULLS LAST, i.id
                """),
                {"id": event_id},
            ).mappings()
        )
        return {
            "event_type": "post",
            **dict(post),
            "revisions": revisions,
            "media": merge_media((post["content"] or {}).get("media"), media),
            "interactions": interactions,
        }

    story_params = dict(params)
    story_provider_clause = " AND s.provider = :provider" if provider else ""
    story = (
        db.execute(
            text(f"""
          SELECT s.id, s.provider, s.external_id, s.profile_id,
                 s.occurred_at, s.expires_at, s.coverage_status,
                 s.current_content_hash AS content_hash,
                 profiles.display_name AS profile_display_name,
                 co.payload_json AS content
          FROM social_stories s
          LEFT JOIN profiles ON profiles.id = s.profile_id
          LEFT JOIN content_objects co ON co.id = s.content_object_id
          WHERE s.id = :id{story_provider_clause}
        """),
            story_params,
        )
        .mappings()
        .one_or_none()
    )
    if story:
        revisions = list(
            db.execute(
                text("""
                  SELECT content_hash, observed_at
                  FROM social_story_revisions
                  WHERE story_id = :id ORDER BY observed_at DESC, id DESC
                """),
                {"id": event_id},
            ).mappings()
        )
        media = list(
            db.execute(
                text("""
                  SELECT m.id, m.media_type, m.byte_length, m.width, m.height,
                         m.duration_ms, m.capture_at, COALESCE(r.source_url, m.source_record_id) AS source_url
                  FROM media_links l JOIN media_assets m ON m.id = l.media_id
                  LEFT JOIN remote_media_sources r ON r.media_id = m.id
                  WHERE l.entity_type = 'social_story' AND l.entity_id = :id
                  ORDER BY l.role, m.id
                """),
                {"id": event_id},
            ).mappings()
        )
        return {"event_type": "story", **dict(story), "revisions": revisions, "media": media}

    activity = (
        db.execute(
            text("""
          SELECT a.id, 'manual' AS provider, a.id::text AS external_id,
                 a.occurred_at, a.title, a.body AS content, a.activity_type,
                 a.source_type, a.source_record_id, a.created_at
          FROM activities a WHERE a.id = :id
        """),
            {"id": event_id},
        )
        .mappings()
        .one_or_none()
    )
    if activity and (not provider or provider == "manual"):
        participants = list(
            db.execute(
                text("""
                  SELECT p.id, p.display_name, p.profile_type
                  FROM activity_participants ap JOIN profiles p ON p.id = ap.profile_id
                  WHERE ap.activity_id = :id ORDER BY p.display_name
                """),
                {"id": event_id},
            ).mappings()
        )
        return {
            "event_type": "activity",
            **dict(activity),
            "participants": participants,
            "media": [],
        }
    raise HTTPException(status_code=404, detail="timeline event not found")


@app.post("/api/v1/imports/batches", response_model=ImportBatchOut, status_code=201)
async def import_batch(
    payload: ImportBatchRequest,
    request: Request,
    db: Session = Depends(get_db),
    x_import_timestamp: str | None = Header(default=None),
    x_import_nonce: str | None = Header(default=None),
    x_import_signature: str | None = Header(default=None),
    x_import_token: str | None = Header(default=None),
):
    if not (x_import_timestamp and x_import_nonce and x_import_signature):
        raise HTTPException(status_code=401, detail="import signature required")
    signed_body = await request.body()
    if not verify_import_signature(
        x_import_timestamp, x_import_nonce, x_import_signature, signed_body, payload.source
    ):
        raise HTTPException(status_code=401, detail="invalid import signature")
    active_token_count = db.execute(
        text(
            "SELECT count(*) FROM import_service_tokens WHERE source = :source AND revoked_at IS NULL"
        ),
        {"source": payload.source},
    ).scalar_one()
    if active_token_count:
        if not x_import_token:
            raise HTTPException(status_code=401, detail="import service token required")
        token_row = db.execute(
            text("""
              SELECT id FROM import_service_tokens
              WHERE source = :source AND token_hash = :token_hash AND revoked_at IS NULL
            """),
            {"source": payload.source, "token_hash": hash_service_token(x_import_token)},
        ).scalar_one_or_none()
        if not token_row:
            raise HTTPException(status_code=401, detail="invalid import service token")
        db.execute(
            text("UPDATE import_service_tokens SET last_used_at = now() WHERE id = :id"),
            {"id": token_row},
        )
    db.execute(text("DELETE FROM import_request_nonces WHERE expires_at < now()"))
    accepted_nonce = db.execute(
        text("""
          INSERT INTO import_request_nonces(nonce, expires_at)
          VALUES (:nonce, now() + (:ttl || ' seconds')::interval)
          ON CONFLICT (nonce) DO NOTHING
          RETURNING nonce
        """),
        {"nonce": x_import_nonce, "ttl": settings.import_signature_ttl_seconds},
    ).scalar_one_or_none()
    if not accepted_nonce:
        raise HTTPException(status_code=409, detail="replayed import request")
    result = project_batch(db, payload)
    db.commit()
    return result


@app.get("/api/v1/imports/batches", response_model=list[ImportBatchOut])
def imports(db: Session = Depends(get_db), _user=Depends(current_user)):
    return list_batches(db)


@app.get("/api/v1/imports/reconciliation")
def import_reconciliation(db: Session = Depends(get_db), _user=Depends(current_user)):
    return {
        'sources':[dict(r) for r in db.execute(text('SELECT * FROM source_reconciliation ORDER BY source,stream')).mappings()],
        'media':[dict(r) for r in db.execute(text('SELECT state,count(*) AS count FROM media_manifest GROUP BY state ORDER BY state')).mappings()],
        'jobs':[dict(r) for r in db.execute(text("SELECT job_type,status,count(*) AS count FROM jobs GROUP BY job_type,status ORDER BY job_type,status")).mappings()],
        'messages':dict(db.execute(text("SELECT count(*) AS processed_tables,COALESCE(sum(source_count),0) AS source_rows,COALESCE(sum(projected_count),0) AS processed_rows FROM message_source_cursors")).mappings().one()),
    }


@app.post("/api/v1/imports/tokens", status_code=201)
def create_import_service_token(
    payload: ImportServiceTokenCreate,
    db: Session = Depends(get_db),
    user=Depends(current_user),
):
    raw_token = new_token()
    row = (
        db.execute(
            text("""
              INSERT INTO import_service_tokens(source, label, token_hash)
              VALUES (:source, :label, :token_hash)
              RETURNING id, source, label, created_at
            """),
            {
                "source": payload.source,
                "label": payload.label,
                "token_hash": hash_service_token(raw_token),
            },
        )
        .mappings()
        .one()
    )
    db.execute(
        text(
            "INSERT INTO audit_events(user_id, action, entity_type, entity_id, metadata) VALUES (:user, 'import.token.created', 'import_service_token', :id, CAST(:metadata AS jsonb))"
        ),
        {
            "user": user["id"],
            "id": row["id"],
            "metadata": json.dumps({"source": payload.source, "label": payload.label}),
        },
    )
    db.commit()
    return {**dict(row), "token": raw_token}


@app.get("/api/v1/imports/tokens")
def list_import_service_tokens(db: Session = Depends(get_db), _user=Depends(current_user)):
    return list(
        db.execute(
            text("""
              SELECT id, source, label, created_at, last_used_at, revoked_at
              FROM import_service_tokens ORDER BY created_at DESC
            """)
        ).mappings()
    )


@app.post("/api/v1/imports/tokens/{token_id}/revoke")
def revoke_import_service_token(
    token_id: UUID,
    db: Session = Depends(get_db),
    user=Depends(current_user),
):
    revoked = db.execute(
        text("""
          UPDATE import_service_tokens SET revoked_at = now()
          WHERE id = :id AND revoked_at IS NULL RETURNING id
        """),
        {"id": token_id},
    ).scalar_one_or_none()
    if not revoked:
        raise HTTPException(status_code=404, detail="import token not found")
    db.execute(
        text(
            "INSERT INTO audit_events(user_id, action, entity_type, entity_id) VALUES (:user, 'import.token.revoked', 'import_service_token', :id)"
        ),
        {"user": user["id"], "id": token_id},
    )
    db.commit()
    return {"status": "revoked"}


@app.get("/api/v1/imports/batches/{batch_id}")
def import_batch_detail(batch_id: str, db: Session = Depends(get_db), _user=Depends(current_user)):
    row = (
        db.execute(
            text("""
              SELECT b.*, co.payload_json AS raw_manifest, co.storage_uri AS raw_manifest_uri
              FROM import_batches b
              LEFT JOIN content_objects co ON co.id = b.raw_manifest_object_id
              WHERE b.batch_id = :batch_id
            """),
            {"batch_id": batch_id},
        )
        .mappings()
        .one_or_none()
    )
    if not row:
        raise HTTPException(status_code=404, detail="batch not found")
    return dict(row)


@app.post("/api/v1/imports/batches/{batch_id}/replay")
def replay_import_batch(batch_id: str, db: Session = Depends(get_db), _user=Depends(current_user)):
    raw_row = (
        db.execute(
            text("""
          SELECT co.payload_json, co.storage_uri
          FROM import_batches b JOIN content_objects co ON co.id = b.raw_manifest_object_id
          WHERE b.batch_id = :batch_id
        """),
            {"batch_id": batch_id},
        )
        .mappings()
        .one_or_none()
    )
    raw = raw_row["payload_json"] if raw_row else None
    if raw is None and raw_row and raw_row["storage_uri"]:
        manifest_path = Path(raw_row["storage_uri"])
        if manifest_path.is_file():
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not raw:
        raise HTTPException(status_code=404, detail="replay manifest not found")
    try:
        from .imports import hydrate_manifest
        request_payload = ImportBatchRequest.model_validate(hydrate_manifest(raw))
    except Exception as exc:
        raise HTTPException(status_code=422, detail="stored manifest is not replayable") from exc
    result = project_batch(db, request_payload)
    db.commit()
    return result


@app.get("/api/v1/imports/cursors")
def import_cursors(db: Session = Depends(get_db), _user=Depends(current_user)):
    return list(
        db.execute(
            text("""
              SELECT source, stream, cursor_value, batch_id, updated_at
              FROM source_cursors ORDER BY source, stream
            """)
        ).mappings()
    )


@app.get("/api/v1/imports/jobs")
def import_jobs(
    status_filter: str | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
    _user=Depends(current_user),
):
    clauses = ["1 = 1"]
    params: dict[str, object] = {"limit": min(max(limit, 1), 200)}
    if status_filter:
        clauses.append("status = :status")
        params["status"] = status_filter
    return list(
        db.execute(
            text(f"""
              SELECT id, job_type, payload, status, attempts, available_at,
                     locked_at, completed_at, error
              FROM jobs WHERE {" AND ".join(clauses)}
              ORDER BY available_at DESC LIMIT :limit
            """),
            params,
        ).mappings()
    )


@app.get("/api/v1/imports/events")
def import_events(limit: int = 100, db: Session = Depends(get_db), _user=Depends(current_user)):
    return list(
        db.execute(
            text("""
              SELECT id, source, stream, external_id, batch_id, source_cursor,
                     content_hash, observed_at, state, source_updated_at
              FROM source_observations ORDER BY observed_at DESC LIMIT :limit
            """),
            {"limit": min(max(limit, 1), 200)},
        ).mappings()
    )


@app.get("/api/v1/timeline")
def timeline(
    profile_id: UUID | None = None,
    provider: str | None = None,
    before: datetime | None = None,
    after: datetime | None = None,
    limit: int = 50,
    cursor: str | None = None,
    db: Session = Depends(get_db),
    _user=Depends(current_user),
):
    post_clauses = ["1 = 1"]
    story_clauses = ["1 = 1"]
    activity_clauses = ["activities.activity_type NOT IN ('wechat_direct_summary','wechat_group_summary')"]
    params: dict[str, object] = {
        "limit": min(max(limit, 1), 100),
        "profile_id": profile_id,
    }
    if cursor:
        try:
            stamp, event_id = json.loads(base64.urlsafe_b64decode(cursor.encode()))
            params['cursor_id'] = UUID(event_id)
            params['cursor_time'] = datetime.fromisoformat(stamp) if stamp else None
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=422, detail="invalid cursor") from exc
        for table, clauses in [('social_posts',post_clauses),('social_stories',story_clauses),('activities',activity_clauses)]:
            if stamp:
                clauses.append(f"({table}.occurred_at < :cursor_time OR {table}.occurred_at IS NULL OR ({table}.occurred_at=:cursor_time AND {table}.id<:cursor_id))")
            else:
                clauses.append(f"({table}.occurred_at IS NULL AND {table}.id<:cursor_id)")
    if after:
        for table, clauses in [('social_posts',post_clauses),('social_stories',story_clauses),('activities',activity_clauses)]:
            clauses.append(f"{table}.occurred_at >= :after")
        params['after'] = after
    if before:
        post_clauses.append("social_posts.occurred_at < :before")
        story_clauses.append("social_stories.occurred_at < :before")
        activity_clauses.append("activities.occurred_at < :before")
        params["before"] = before
    if profile_id:
        post_clauses.append("social_posts.profile_id = :profile_id")
        story_clauses.append("social_stories.profile_id = :profile_id")
        activity_clauses.append(
            "EXISTS (SELECT 1 FROM activity_participants ap WHERE ap.activity_id = activities.id AND ap.profile_id = :profile_id)"
        )
    if provider:
        post_clauses.append("social_posts.provider = :provider")
        story_clauses.append("social_stories.provider = :provider")
        params["provider"] = provider
        if provider != "manual":
            activity_clauses.append("FALSE")
    rows = list(
        db.execute(
            text(f"""
      SELECT social_posts.id, social_posts.provider, social_posts.external_id,
             social_posts.occurred_at, CASE social_posts.provider WHEN 'wechat' THEN '朋友圈' WHEN 'instagram' THEN 'Instagram 动态' ELSE 'LinkedIn 动态' END AS title,
             social_posts.profile_id, (SELECT display_name FROM profiles WHERE id=social_posts.profile_id) AS profile_name,
             (SELECT avatar_media_id FROM profiles WHERE id=social_posts.profile_id) AS avatar_media_id,
             COALESCE(content_objects.payload_json->>'caption',
                      content_objects.payload_json->>'text',
                      content_objects.payload_json->>'title') AS summary,
             social_posts.current_content_hash AS content_hash,
             COALESCE(jsonb_array_length(COALESCE(content_objects.payload_json->'media', '[]'::jsonb)), 0) AS media_count,
             COALESCE(NULLIF(content_objects.payload_json->>'like_count', '')::int, 0) AS like_count,
             COALESCE(NULLIF(content_objects.payload_json->>'comment_count', '')::int, 0) AS comment_count,
             content_objects.payload_json->'location' AS location,
             COALESCE(content_objects.payload_json->'media', '[]'::jsonb) AS media
      FROM (SELECT * FROM social_posts WHERE {" AND ".join(post_clauses)} ORDER BY occurred_at DESC NULLS LAST,id DESC LIMIT :limit) AS social_posts
      LEFT JOIN content_objects ON content_objects.id = social_posts.content_object_id
      WHERE {" AND ".join(post_clauses)}
      UNION ALL
      SELECT social_stories.id, social_stories.provider, social_stories.external_id,
             social_stories.occurred_at, social_stories.provider || ' story' AS title,
             social_stories.profile_id, (SELECT display_name FROM profiles WHERE id=social_stories.profile_id) AS profile_name,
             (SELECT avatar_media_id FROM profiles WHERE id=social_stories.profile_id) AS avatar_media_id,
             COALESCE(content_objects.payload_json->>'caption',
                      content_objects.payload_json->>'text',
                      social_stories.coverage_status) AS summary,
             social_stories.current_content_hash AS content_hash,
             COALESCE(jsonb_array_length(COALESCE(content_objects.payload_json->'media', '[]'::jsonb)), 0) AS media_count,
             0 AS like_count,
             0 AS comment_count,
             content_objects.payload_json->'location' AS location,
             COALESCE(content_objects.payload_json->'media', '[]'::jsonb) AS media
      FROM (SELECT * FROM social_stories WHERE {" AND ".join(story_clauses)} ORDER BY occurred_at DESC NULLS LAST,id DESC LIMIT :limit) AS social_stories
      LEFT JOIN content_objects ON content_objects.id = social_stories.content_object_id
      WHERE {" AND ".join(story_clauses)}
      UNION ALL
      SELECT activities.id, 'manual' AS provider, activities.id::text AS external_id,
             activities.occurred_at, activities.title, NULL::uuid AS profile_id, NULL::text AS profile_name, NULL::uuid AS avatar_media_id, activities.body AS summary,
             ''::text AS content_hash,
             0 AS media_count,
             0 AS like_count,
             0 AS comment_count,
             NULL::jsonb AS location,
             '[]'::jsonb AS media
      FROM activities
      WHERE {" AND ".join(activity_clauses)}
      ORDER BY occurred_at DESC NULLS LAST, id DESC LIMIT :limit
    """),
            params,
        ).mappings()
    )

    media_by_event = linked_media(db, [row["id"] for row in rows])
    return [
        {**dict(row), "cursor": base64.urlsafe_b64encode(json.dumps([row["occurred_at"].isoformat() if row["occurred_at"] else None, str(row["id"])]).encode()).decode(), "media": merge_media(row["media"], media_by_event.get(str(row["id"]), []))}
        for row in rows
    ]


@app.get("/api/v1/metrics/people-overview")
def people_overview(db: Session = Depends(get_db), _user=Depends(current_user)):
    counts = db.execute(text("SELECT count(*) FILTER(WHERE profile_type='person') AS people, count(*) FILTER(WHERE profile_type='group') AS groups FROM profiles WHERE archived_at IS NULL")).mappings().one()
    result = dict(counts)
    for name, table, entity, fk in [('companies','profile_employment_revisions','companies','company_id'),('schools','profile_education_revisions','schools','school_id')]:
        result[name] = list(db.execute(text(f"""SELECT e.name,count(DISTINCT c.profile_id) AS count
            FROM profile_structured_current c JOIN {table} r ON r.id=c.current_revision_id
            JOIN {entity} e ON e.id=r.{fk} JOIN profiles p ON p.id=c.profile_id AND p.archived_at IS NULL
            GROUP BY e.name ORDER BY count DESC,e.name LIMIT 8""")).mappings())
    return result


@app.get('/api/v1/profiles/{profile_id}/moments-circle')
def profile_moments_circle(profile_id: UUID, db: Session=Depends(get_db), _user=Depends(current_user)):
    owner=get_profile(db,profile_id)
    if not owner:raise HTTPException(status_code=404,detail='profile not found')
    if owner['profile_type']!='person':raise HTTPException(status_code=422,detail='Moments belong to people, not groups')
    from .graph import circle_projection
    return circle_projection(db,settings.raw_root,profile_id)


@app.get('/api/v1/metrics/social')
def social_statistics(profile_id: UUID | None=None, db: Session=Depends(get_db), _user=Depends(current_user)):
    from .social_analytics import social_analytics
    return social_analytics(db,profile_id)
