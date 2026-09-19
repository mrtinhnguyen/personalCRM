"""Source-first ingestion; CRM rows are replaceable indexes of linked accounts."""
from uuid import UUID

from sqlalchemy import text

from .platform_store import PROVIDERS, ensure_account, observe_many, platform_engine


def enabled(db,provider):
    if provider not in PROVIDERS:return False
    return bool(db.execute(text('SELECT enabled FROM platform_migration_state WHERE provider=:provider'),{'provider':provider}).scalar_one_or_none())


def prepare_records(db,request):
    """Persist one source batch before applying its rebuildable CRM projection.

    Account links stay locked for the CRM transaction. Source commits are per
    batch, rather than per record, so a NAS does not fsync hundreds of times for
    a single import. Stable observation IDs make a later CRM failure replayable.
    """
    provider=request.source
    if not enabled(db,provider):return request.records
    db.execute(text('SELECT pg_advisory_xact_lock_shared(11803295)'))
    from .platform_migrate import account_lookup
    context=db.info.setdefault('source_lookup',{})
    if provider not in context:context[provider]=account_lookup(db,provider)
    records=[];observations=[];links={};seen={}
    with platform_engine(provider).begin() as source:
        for record in request.records:
            prepared,values=_prepare_record(db,source,record,request,context[provider],links)
            records.append(prepared)
            for value in values:
                key=(str(value['account']),value['kind'],value['external_id'],value['source_event'])
                if key in seen:
                    if seen[key]!=value['value']:raise ValueError('Observation ID was reused with different content')
                    continue
                seen[key]=value['value'];observations.append(value)
        observe_many(source,observations)
    return records


def _prepare_record(db,source,record,request,lookup,links):
    """Never infer links from names or create people for new platform accounts."""
    from .platform_migrate import resolve_account
    provider=request.source
    _,aliases,profiles=lookup
    content=record.content if isinstance(record.content,dict) else {}
    kind=record.entity_type or ('post' if request.stream in ('posts','moments') else 'story' if request.stream=='stories' else 'profile')
    owner=record.source_account_external_id or (content.get('username') or str((content.get('owner') or {}).get('id') or '') if kind in ('post','story') else record.external_id)
    if kind in ('post','story') and owner:
        from .profile_presentation import identity_key
        aid=aliases.get(owner) or aliases.get(identity_key(provider,owner))
    else:aid=resolve_account(provider,owner,str(content.get('field_key','')),record.profile_id,aliases,profiles)
    if not aid:
        if not owner:raise ValueError('Source account ID is missing; leave the batch for import review')
        from .profile_presentation import identity_key
        external=identity_key(provider,owner)
        if not external:raise ValueError('An explicit source account ID is required')
        object_kind='group' if provider=='wechat' and external.endswith('@chatroom') else 'person'
        aid=ensure_account(source,provider,external,kind=object_kind)
        db.execute(text('''INSERT INTO source_accounts(id,provider,external_id,object_kind,display_name,migrated_at)
            VALUES(:id,:provider,:external,:kind,:external,now()) ON CONFLICT DO NOTHING'''),
            {'id':aid,'provider':provider,'external':external,'kind':object_kind})
        aliases[external]=str(aid)
    aid=str(aid)
    if aid not in links:
        db.execute(text('SELECT id FROM source_accounts WHERE id=:id FOR UPDATE'),{'id':aid})
        links[aid]=db.execute(text('SELECT profile_id FROM source_account_links WHERE account_id=:id'),{'id':aid}).scalar_one_or_none()
    pid=links[aid]
    event='batch:'+request.idempotency_key+':'+record.external_id
    records=[{'account':aid,'kind':kind,'external_id':record.external_id,'value':record.content,
              'source_event':event,'observed_at':request.observed_at,'occurred_at':record.occurred_at}]
    fields=content.get('fields') or ({content['field_key']:content.get('value')} if content.get('field_key') else {})
    for field,value in fields.items():
        records.append({'account':aid,'kind':'field','external_id':field,'value':value,'source_event':event+':'+field,'observed_at':request.observed_at})
    return record.model_copy(update={'profile_id':pid,'source_account_id':UUID(aid),'source_is_authoritative':True}),records


def finish_record(db,record,request):
    aid=getattr(record,'source_account_id',None)
    if not aid:return
    args={'account':aid,'profile':record.profile_id,'source':request.source,'external':record.external_id}
    for table in ('social_posts','social_stories'):
        db.execute(text(f'''UPDATE {table} SET source_account_id=:account,profile_id=:profile
            WHERE provider=:source AND external_id=:external
              AND (source_account_id,profile_id) IS DISTINCT FROM (CAST(:account AS uuid),CAST(:profile AS uuid))'''),args)
    db.execute(text('''UPDATE social_interactions s SET author_account_id=i.source_account_id,
        author_profile_id=i.profile_id FROM identities i WHERE s.provider=:source AND i.provider=:source
        AND s.author_external_id=i.external_id AND i.source_account_id IS NOT NULL
        AND (s.author_account_id,s.author_profile_id) IS DISTINCT FROM (i.source_account_id,i.profile_id)
        AND i.status NOT IN ('invalid','merged') AND s.post_id IN
          (SELECT id FROM social_posts WHERE provider=:source AND external_id=:external)'''),args)
    content=record.content if isinstance(record.content,dict) else {}
    kind=record.entity_type or ('post' if request.stream in ('posts','moments') else 'story' if request.stream=='stories' else 'profile')
    # A post changes its own content and interactions, not every profile field
    # and job/school revision on its author's account.
    if kind in ('post','story') and not any(content.get(key) for key in ('fields','field_key','address','employment','education')):
        return
    if record.profile_id:
        db.execute(text('''UPDATE profile_field_revisions SET source_account_id=:account
            WHERE profile_id=:profile AND source_type=:source AND source_record_id=:external AND source_account_id IS NULL'''),args)
        db.execute(text('''UPDATE profile_field_current c SET source_account_id=r.source_account_id FROM profile_field_revisions r
            WHERE c.current_revision_id=r.id AND r.source_account_id=:account
              AND c.source_account_id IS DISTINCT FROM r.source_account_id'''),args)
        db.execute(text('''INSERT INTO source_account_fields(account_id,field_key,revision_id)
            SELECT :account,c.field_key,c.current_revision_id FROM profile_field_current c WHERE c.source_account_id=:account
            ON CONFLICT(account_id,field_key) DO UPDATE SET revision_id=EXCLUDED.revision_id
            WHERE source_account_fields.revision_id IS DISTINCT FROM EXCLUDED.revision_id'''),args)
        for kind in ('address','employment','education'):
            db.execute(text(f'''UPDATE profile_{kind}_revisions SET source_account_id=:account
                WHERE profile_id=:profile AND source_type=:source AND source_record_id=:external AND source_account_id IS NULL'''),args)
            db.execute(text(f'''UPDATE profile_structured_current c SET source_account_id=:account FROM profile_{kind}_revisions r
                WHERE c.current_revision_id=r.id AND r.source_account_id=:account
                  AND c.source_account_id IS DISTINCT FROM CAST(:account AS uuid)'''),args)
        db.execute(text('''INSERT INTO source_account_facts(account_id,fact_type,fact_key,revision_id)
            SELECT :account,c.fact_type,c.fact_key,c.current_revision_id FROM profile_structured_current c WHERE c.source_account_id=:account
            ON CONFLICT(account_id,fact_type,fact_key) DO UPDATE SET revision_id=EXCLUDED.revision_id
            WHERE source_account_facts.revision_id IS DISTINCT FROM EXCLUDED.revision_id'''),args)
