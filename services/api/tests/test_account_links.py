import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from test_media_integration import db as db  # noqa: PLC0414 -- shared pytest fixture

from app.account_links import set_link
from app.imports import project_batch
from app.platform_migrate import register_accounts
from app.repositories import append_field_revision, list_field_history
from app.schemas import ImportBatchRequest


@pytest.fixture
def source_engine(monkeypatch):
    url=make_url(os.environ['TEST_DATABASE_URL']);name='account_test_'+uuid4().hex
    admin=create_engine(url.set(database='postgres'),isolation_level='AUTOCOMMIT')
    with admin.connect() as c:c.exec_driver_sql(f'CREATE DATABASE "{name}"')
    engine=create_engine(url.set(database=name))
    with engine.begin() as c:c.execute(text((Path(__file__).parents[1]/'app/platform_schema.sql').read_text()))
    monkeypatch.setattr('app.platform_store.platform_engine',lambda _:engine)
    monkeypatch.setattr('app.platform_migrate.platform_engine',lambda _:engine)
    monkeypatch.setattr('app.source_projection.platform_engine',lambda _:engine)
    yield engine
    engine.dispose()
    with admin.connect() as c:c.exec_driver_sql(f'DROP DATABASE "{name}" WITH (FORCE)')
    admin.dispose()


def test_unlink_relink_preserves_source_and_manual_records_and_unlinked_aba(db,source_engine):
    original,target,group=uuid4(),uuid4(),uuid4()
    for pid,kind in [(original,'person'),(target,'person'),(group,'group')]:
        db.execute(text("INSERT INTO profiles(id,profile_type,display_name,summary) VALUES(:id,:type,'Same display name','Handwritten summary')"),{'id':pid,'type':kind})
    db.execute(text("INSERT INTO identities(profile_id,provider,external_id) VALUES(:id,'linkedin','actual-account')"),{'id':original})
    register_accounts(db,'linkedin')
    aid=db.execute(text('SELECT id FROM source_accounts')).scalar_one()
    db.execute(text('UPDATE source_accounts SET migrated_at=now()'))
    db.execute(text("INSERT INTO platform_migration_state(provider,enabled) VALUES('linkedin',true)"))
    append_field_revision(db,profile_id=original,field_key='note',value='Personal note',source_type='manual',operation='manual_edit')
    def submit(batch,value,post=False):
        content={'text':value} if post else {'fields':{'linkedin.about':value,'linkedin.location':value},'education':[{'school':'School','degree':value,'id':'school-1'}]}
        request=ImportBatchRequest(source='linkedin',stream='posts' if post else 'profiles',batch_id=batch,idempotency_key=batch,observed_at=datetime.now(UTC),
            records=[{'external_id':'post-1' if post else 'actual-account','profile_id':original,'entity_type':'post' if post else 'profile','content':{**content,'username':'actual-account'}}])
        project_batch(db,request)
    submit('first','A');submit('post','Original post',True)
    db.commit()
    assert db.execute(text("SELECT value FROM profile_metric_values WHERE field_key='linkedin.location'")).scalar_one()=='A'
    with source_engine.connect() as c:
        before={table:c.execute(text(f'SELECT count(*) FROM {table}')).scalar_one() for table in ('objects','payloads','revisions','observations')}
    set_link(db,aid,None,expected_profile_id=original);db.commit()
    assert db.execute(text('SELECT profile_id FROM social_posts')).scalar_one() is None
    assert db.execute(text("SELECT count(*) FROM profile_field_current WHERE profile_id=:id AND field_key='linkedin.about'"),{'id':original}).scalar_one()==0
    assert db.execute(text('SELECT count(*) FROM profile_structured_current WHERE profile_id=:id'),{'id':original}).scalar_one()==0
    assert db.execute(text('SELECT count(*) FROM profile_metric_values')).scalar_one()==0
    assert [r['field_key'] for r in list_field_history(db,original)]==['note']
    assert db.execute(text('SELECT count(*) FROM profiles WHERE archived_at IS NOT NULL')).scalar_one()==0
    with source_engine.connect() as c:
        assert before=={table:c.execute(text(f'SELECT count(*) FROM {table}')).scalar_one() for table in before}
    # Incoming records may still carry the former Profile ID. It must never
    # recreate the link, skip a transition, or copy unchanged values.
    submit('second','B');submit('third','A');submit('unchanged','A');submit('post-change','Edited while unlinked',True)
    assert db.execute(text('SELECT count(*) FROM profile_metric_values')).scalar_one()==0
    assert db.execute(text('SELECT count(*) FROM source_account_links')).scalar_one()==0
    assert db.execute(text('SELECT profile_id FROM social_posts')).scalar_one() is None
    assert db.execute(text("SELECT count(*) FROM profile_field_revisions WHERE field_key='linkedin.about'")).scalar_one()==3
    set_link(db,aid,target,expected_profile_id=None);db.commit()
    metric=db.execute(text("SELECT profile_id,value FROM profile_metric_values WHERE field_key='linkedin.location'")).one()
    assert metric.profile_id==target and metric.value=='A'
    assert db.execute(text('SELECT profile_id FROM social_posts')).scalar_one()==target
    assert len([r for r in list_field_history(db,target) if r['field_key']=='linkedin.about'])==3
    assert db.execute(text('SELECT count(*) FROM profile_structured_current WHERE profile_id=:id'),{'id':target}).scalar_one()==1
    assert db.execute(text('SELECT summary FROM profiles WHERE id=:id'),{'id':original}).scalar_one()=='Handwritten summary'
    assert db.execute(text('SELECT count(*) FROM profiles')).scalar_one()==3
    with pytest.raises(HTTPException) as conflict:set_link(db,aid,original,expected_profile_id=None)
    assert conflict.value.status_code==409
    with pytest.raises(HTTPException) as mismatch:set_link(db,aid,group,expected_profile_id=target)
    assert mismatch.value.status_code==422
    set_link(db,aid,original,expected_profile_id=target);db.commit()
    assert db.execute(text('SELECT count(*) FROM profile_field_current WHERE profile_id=:id'),{'id':target}).scalar_one()==0
    assert db.execute(text('SELECT profile_id FROM social_posts')).scalar_one()==original


def test_new_source_account_waits_for_link_and_media_follows_account(db,source_engine,tmp_path):
    import hashlib

    from app.remote_media import materialize_image
    db.execute(text("INSERT INTO platform_migration_state(provider,enabled) VALUES('instagram',true)"))
    request=ImportBatchRequest(source='instagram',stream='profiles',batch_id='new',idempotency_key='new',observed_at=datetime.now(UTC),
        records=[{'external_id':'real_ig_account','content':{'fields':{'instagram.biography':'A new biography'}}}])
    project_batch(db,request);db.commit()
    assert db.execute(text('SELECT count(*) FROM profiles')).scalar_one()==0
    aid=db.execute(text('SELECT id FROM source_accounts')).scalar_one()
    assert db.execute(text('SELECT count(*) FROM source_account_links')).scalar_one()==0
    image=tmp_path/'test-image.jpg';image.write_bytes(b'image bytes')
    digest=hashlib.sha256(image.read_bytes()).hexdigest()
    media=materialize_image(db,{'entity_type':'source_account','entity_id':str(aid),'role':'instagram_avatar',
        'url':'https://cdninstagram.com/test.jpg','download_key':'first'},tmp_path,downloaded=(digest,str(image),image.stat().st_size,'image/jpeg'))
    original,target=uuid4(),uuid4()
    for pid in (original,target):db.execute(text("INSERT INTO profiles(id,profile_type,display_name) VALUES(:id,'person','Same name')"),{'id':pid})
    set_link(db,aid,original,expected_profile_id=None)
    assert str(db.execute(text('SELECT avatar_media_id FROM profiles WHERE id=:id'),{'id':original}).scalar_one())==media
    set_link(db,aid,target,expected_profile_id=original)
    assert db.execute(text('SELECT avatar_media_id FROM profiles WHERE id=:id'),{'id':original}).scalar_one() is None
    assert str(db.execute(text('SELECT avatar_media_id FROM profiles WHERE id=:id'),{'id':target}).scalar_one())==media
    assert db.execute(text('SELECT count(*) FROM media_assets')).scalar_one()==1
    with source_engine.connect() as c:
        assert c.execute(text('SELECT count(*) FROM media')).scalar_one()==1
        assert c.execute(text('SELECT count(*) FROM media_links')).scalar_one()==1


def test_source_batch_commits_once_and_replays_after_crm_failure(db,source_engine,monkeypatch):
    from sqlalchemy import event

    from app import imports

    person=uuid4()
    db.execute(text("INSERT INTO profiles(id,profile_type,display_name) VALUES(:id,'person','Recorded person')"),{'id':person})
    db.execute(text("INSERT INTO identities(profile_id,provider,external_id) VALUES(:id,'instagram','actual_account')"),{'id':person})
    register_accounts(db,'instagram')
    db.execute(text("INSERT INTO platform_migration_state(provider,enabled) VALUES('instagram',true)"));db.commit()
    commits=[]
    def committed(connection):commits.append(True)
    event.listen(source_engine,'commit',committed)
    records=[{'external_id':f'post-{n}','source_account_external_id':'actual_account','entity_type':'post',
        'content':{'text':f'Observed post {n}'}} for n in range(4)]
    # Identical records in a delivery are still one stable source observation.
    records.append(records[0])
    request=ImportBatchRequest(source='instagram',stream='posts',batch_id='atomic-source',
        idempotency_key='atomic-source',observed_at=datetime.now(UTC),records=records)
    project=imports._project_social_record
    def fail_projection(*args):raise RuntimeError('CRM projection interrupted after source commit')
    monkeypatch.setattr(imports,'_project_social_record',fail_projection)
    with pytest.raises(RuntimeError,match='interrupted'):project_batch(db,request)
    db.rollback()
    assert len(commits)==1
    with source_engine.connect() as source:
        assert source.execute(text('SELECT count(*) FROM objects')).scalar_one()==4
        assert source.execute(text('SELECT count(*) FROM revisions')).scalar_one()==4
    assert db.execute(text('SELECT count(*) FROM social_posts')).scalar_one()==0
    monkeypatch.setattr(imports,'_project_social_record',project)
    project_batch(db,request);db.commit()
    assert len(commits)==2
    assert db.execute(text('SELECT count(*) FROM social_posts')).scalar_one()==4
    project_batch(db,request);db.commit()
    assert len(commits)==2  # A complete retry does not reopen the source transaction.
    with source_engine.connect() as source:
        assert source.execute(text('SELECT count(*) FROM revisions')).scalar_one()==4
        assert source.execute(text('SELECT count(*) FROM observations')).scalar_one()==4
    event.remove(source_engine,'commit',committed)


def test_ordered_field_transitions_in_one_source_batch_are_not_collapsed(db,source_engine):
    person=uuid4()
    db.execute(text("INSERT INTO profiles(id,profile_type,display_name) VALUES(:id,'person','Same name')"),{'id':person})
    db.execute(text("INSERT INTO identities(profile_id,provider,external_id) VALUES(:id,'linkedin','actual-account')"),{'id':person})
    register_accounts(db,'linkedin')
    db.execute(text("INSERT INTO platform_migration_state(provider,enabled) VALUES('linkedin',true)"))
    request=ImportBatchRequest(source='linkedin',stream='profiles',batch_id='ordered',idempotency_key='ordered',
        observed_at=datetime.now(UTC),records=[{'external_id':f'observation-{n}',
            'source_account_external_id':'actual-account','content':{'fields':{'linkedin.about':value}}}
            for n,value in enumerate(('A','B','A','A'))])
    project_batch(db,request);db.commit()
    with source_engine.connect() as source:
        values=source.execute(text("SELECT p.value FROM revisions r JOIN objects o ON o.id=r.object_id JOIN payloads p ON p.sha256=r.content_hash WHERE o.object_kind='field' ORDER BY r.revision_number")).scalars().all()
        assert values==['A','B','A']
    history=[r['value'] for r in list_field_history(db,person) if r['field_key']=='linkedin.about']
    assert len(history)==3 and history.count('A')==2 and history.count('B')==1
    assert db.execute(text('SELECT count(*) FROM profiles')).scalar_one()==1


def test_archive_batch_keeps_post_media_on_unlinked_source_accounts(db,source_engine,tmp_path):
    from app.archive_media import link, register_file
    from app.platform_store import object_id
    from app.remote_media import retain_post_media_batch

    db.execute(text("INSERT INTO platform_migration_state(provider,enabled) VALUES('wechat',true)"))
    project_batch(db,ImportBatchRequest(source='wechat',stream='moments',batch_id='photos',idempotency_key='photos',
        observed_at=datetime.now(UTC),records=[{'external_id':'post','source_account_external_id':'wxid_actual',
            'entity_type':'post','content':{'text':'Independent archive'}}]));db.commit()
    post,account=db.execute(text('SELECT id,source_account_id FROM social_posts')).one()
    pending=[]
    for n in range(2):
        path=tmp_path/f'{n}.jpg';path.write_bytes(b'\xff\xd8\xff'+bytes([n]))
        media=register_file(db,path,tmp_path/'media','wechat');role=f'media-{n+1}'
        link(db,media,post,role,retain=False)
        pending.append({'post':str(post),'media':str(media),'role':role})
    retain_post_media_batch(db,pending)
    db.rollback()  # Source committed, CRM registration/linking did not.
    pending=[]
    for n in range(2):
        media=register_file(db,tmp_path/f'{n}.jpg',tmp_path/'media','wechat');role=f'media-{n+1}'
        link(db,media,post,role,retain=False)
        pending.append({'post':str(post),'media':str(media),'role':role})
    retain_post_media_batch(db,pending);db.commit()
    assert db.execute(text('SELECT count(*) FROM profiles')).scalar_one()==0
    assert db.execute(text('SELECT count(*) FROM media_links')).scalar_one()==2
    with source_engine.connect() as source:
        assert source.execute(text('SELECT count(*) FROM media')).scalar_one()==2
        assert source.execute(text('SELECT count(*) FROM media_links WHERE object_id=:id'),
            {'id':object_id(account,'post','post')}).scalar_one()==2


def test_group_membership_survives_unlink_of_one_of_two_person_accounts(db,source_engine):
    person,group=uuid4(),uuid4()
    for pid,kind in [(person,'person'),(group,'group')]:
        db.execute(text("INSERT INTO profiles(id,profile_type,display_name) VALUES(:id,:kind,'Account test')"),{'id':pid,'kind':kind})
    for ext,pid,provider in [('wxid_a',person,'wechat'),('wxid_b',person,'wechat'),('123@chatroom',group,'wechat_group')]:
        db.execute(text('INSERT INTO identities(external_id,profile_id,provider) VALUES(:ext,:pid,:provider)'),{'ext':ext,'pid':pid,'provider':provider})
    register_accounts(db,'wechat')
    accounts=dict(db.execute(text('SELECT external_id,id FROM source_accounts')).all())
    db.execute(text('UPDATE source_accounts SET migrated_at=now()'))
    for ext in ('wxid_a','wxid_b'):
        db.execute(text('INSERT INTO source_group_memberships(group_account_id,person_account_id) VALUES(:g,:p)'),{'g':accounts['123@chatroom'],'p':accounts[ext]})
    db.execute(text('INSERT INTO group_memberships(group_profile_id,person_profile_id) VALUES(:g,:p)'),{'g':group,'p':person})
    set_link(db,accounts['wxid_a'],None,expected_profile_id=person)
    assert db.execute(text('SELECT count(*) FROM group_memberships')).scalar_one()==1
    set_link(db,accounts['wxid_b'],None,expected_profile_id=person)
    assert db.execute(text('SELECT count(*) FROM group_memberships')).scalar_one()==0
    assert db.execute(text('SELECT count(*) FROM source_group_memberships')).scalar_one()==2
    set_link(db,accounts['wxid_b'],person,expected_profile_id=None)
    assert db.execute(text('SELECT count(*) FROM group_memberships')).scalar_one()==1


def test_archive_media_retains_unlinked_account_and_avatar_aba(db,source_engine,tmp_path):
    from app.archive_media import link, register_file
    from app.platform_store import object_id

    db.execute(text("INSERT INTO platform_migration_state(provider,enabled) VALUES('instagram',true)"))
    project_batch(db,ImportBatchRequest(source='instagram',stream='profiles',batch_id='archive',idempotency_key='archive',observed_at=datetime.now(UTC),
        records=[{'external_id':'archive-account','content':{'fields':{'instagram.biography':'Archived'}}}]))
    aid=db.execute(text('SELECT id FROM source_accounts')).scalar_one()
    media_root=tmp_path/'media';media_root.mkdir()
    assets=[]
    for filename,content in [('a.jpg',b'\xff\xd8\xffone'),('b.jpg',b'\xff\xd8\xfftwo')]:
        path=tmp_path/filename;path.write_bytes(content)
        assets.append(register_file(db,path,media_root,'instagram'))
    for asset in [assets[0],assets[1],assets[0],assets[0]]:
        link(db,asset,aid,'instagram_avatar',entity_type='source_account')
    assert db.execute(text('SELECT count(*) FROM profiles')).scalar_one()==0
    assert db.execute(text('SELECT media_id FROM source_account_media')).scalar_one()==assets[0]
    with source_engine.connect() as source:
        oid=object_id(aid,'profile_media','instagram_avatar')
        assert source.execute(text('SELECT count(*) FROM revisions WHERE object_id=:id'),{'id':oid}).scalar_one()==3
        assert source.execute(text('SELECT count(*) FROM media')).scalar_one()==2
    person=uuid4();db.execute(text("INSERT INTO profiles(id,profile_type,display_name) VALUES(:id,'person','Manual person')"),{'id':person})
    set_link(db,aid,person,expected_profile_id=None)
    assert db.execute(text('SELECT avatar_media_id FROM profiles')).scalar_one()==assets[0]


def test_source_migration_keeps_aba_and_uses_explicit_cover_manifest(db,source_engine,tmp_path):
    import json

    from app.archive_media import link, register_file
    from app.platform_migrate import migrate_fields, migrate_pointers
    from app.platform_store import object_id

    person=uuid4();db.execute(text("INSERT INTO profiles(id,profile_type,display_name) VALUES(:id,'person','Legacy shared profile')"),{'id':person})
    for external in ('wxid_a','wxid_b'):
        db.execute(text("INSERT INTO identities(profile_id,provider,external_id) VALUES(:id,'wechat',:ext)"),{'id':person,'ext':external})
    for value in ['A','B','A']:
        append_field_revision(db,profile_id=person,field_key='wechat.signature',value=value,source_type='wechat',source_record_id='wxid_a',operation='import')
    register_accounts(db,'wechat')
    accounts=dict(db.execute(text('SELECT external_id,id FROM source_accounts')).all())
    report=migrate_fields(db,'wechat')
    assert report['field_revisions_migrated']==3
    assert report['unresolved_field_revision_ids']==[]
    with source_engine.connect() as source:
        oid=object_id(accounts['wxid_a'],'field','wechat.signature')
        assert source.execute(text('SELECT revision_number FROM objects WHERE id=:id'),{'id':oid}).scalar_one()==3
    assert migrate_fields(db,'wechat')['field_revisions_migrated']==0
    file=tmp_path/'cover.jpg';file.write_bytes(b'\xff\xd8\xffcover')
    media_root=tmp_path/'media';media_root.mkdir()
    media=register_file(db,file,media_root,'wechat');link(db,media,person,'cover',entity_type='profile')
    manifest=tmp_path/'manifest.json';manifest.write_text(json.dumps({'wxid_b':{'file':'cover.jpg'}}))
    migrate_pointers(db,'wechat',manifest)
    assert db.execute(text('SELECT account_id FROM source_account_media')).scalar_one()==accounts['wxid_b']


def test_unlinked_instagram_profile_refresh_and_worker_share_source_store(db,source_engine,tmp_path,monkeypatch):
    import hashlib
    import importlib.util
    import json
    from contextlib import contextmanager

    from app.reconcile_sources import instagram_profiles

    db.execute(text("INSERT INTO platform_migration_state(provider,enabled) VALUES('instagram',true)"))
    root=tmp_path/'profiles';directory=root/'source_user';directory.mkdir(parents=True)
    profile=directory/'profile.json'
    profile.write_text(json.dumps({'userid':123456789,'username':'source_user','biography':'A',
                                   'profile_pic_url':'https://cdninstagram.com/avatar.jpg'}))
    assert instagram_profiles(db,root,apply=True)['changed_profiles']==1
    aid=db.execute(text('SELECT id FROM source_accounts')).scalar_one()
    assert db.execute(text('SELECT count(*) FROM profiles')).scalar_one()==0
    avatar_job=db.execute(text("SELECT payload FROM jobs WHERE job_type='media.download'")).scalar_one()
    assert avatar_job['entity_type']=='source_account' and avatar_job['entity_id']==str(aid)
    assert avatar_job['role']=='instagram_avatar'
    assert instagram_profiles(db,root,apply=True)['changed_profiles']==0
    profile.write_text(json.dumps({'userid':123456789,'username':'source_user','biography':'B'}))
    assert instagram_profiles(db,root,apply=True)['changed_profiles']==1
    person=uuid4();db.execute(text("INSERT INTO profiles(id,profile_type,display_name) VALUES(:id,'person','Manual link')"),{'id':person})
    set_link(db,aid,person,expected_profile_id=None)
    assert db.execute(text('SELECT source_account_id FROM identities')).scalar_one()==aid
    spec=importlib.util.spec_from_file_location('source_media_worker',Path(__file__).parents[2]/'worker'/'worker.py')
    worker=importlib.util.module_from_spec(spec);spec.loader.exec_module(worker)
    class TestEngine:
        @contextmanager
        def connect(self):yield db
        begin=connect
    monkeypatch.setattr(worker,'engine',TestEngine())
    db.execute(text("INSERT INTO jobs(job_type,payload,available_at) VALUES('metrics.refresh','{}',now()-interval '1 day')"))
    claimed=worker.claim_job()
    assert claimed['job_type']=='media.download' and claimed['payload']['role']=='instagram_avatar'
    file=tmp_path/'download.jpg';file.write_bytes(b'image bytes')
    digest=hashlib.sha256(file.read_bytes()).hexdigest()
    monkeypatch.setattr(worker,'download_image',lambda *_:(digest,str(file),file.stat().st_size,'image/jpeg'))
    worker.execute_job({'job_type':'media.download','payload':{'url':'https://cdninstagram.com/avatar.jpg',
        'entity_type':'source_account','entity_id':str(aid),'role':'instagram_avatar','download_key':'worker-first'}})
    assert db.execute(text('SELECT avatar_media_id FROM profiles')).scalar_one() is not None
    with source_engine.connect() as source:assert source.execute(text('SELECT count(*) FROM media')).scalar_one()==1


def test_monthly_chat_archive_follows_account_without_message_body_queries(db,source_engine,monkeypatch,tmp_path):
    import json

    from app.chat_months import import_archive, profile_months
    from app.main import message_month_bounds
    monkeypatch.setattr('app.chat_months.platform_engine',lambda _:source_engine)
    original,target=uuid4(),uuid4()
    for pid in (original,target):db.execute(text("INSERT INTO profiles(id,profile_type,display_name) VALUES(:id,'person','Same name')"),{'id':pid})
    db.execute(text("INSERT INTO identities(profile_id,provider,external_id) VALUES(:id,'wechat','wxid_month_owner')"),{'id':original})
    register_accounts(db,'wechat')
    aid=db.execute(text('SELECT id FROM source_accounts')).scalar_one()
    db.execute(text('UPDATE source_accounts SET migrated_at=now()'))
    db.execute(text("INSERT INTO platform_migration_state(provider,enabled) VALUES('wechat',true)"));db.commit()
    row={'id':1,'wechat_username':'wxid_month_owner','month':'2026-03','sent':3,'received':7,'total':10,
         'first_message_at':1772517600,'last_message_at':1772776800,'snapshot_at':'2026-08-21 00:00:00'}
    archive=tmp_path/'months.json';archive.write_text(json.dumps({'timezone':'America/Chicago','rows':[row]}))
    assert import_archive(db,archive)['changed_source_objects']==1
    assert import_archive(db,archive)['changed_source_objects']==0
    assert profile_months(db,original)['total']==10
    assert db.execute(text('SELECT count(*) FROM message_events')).scalar_one()==0
    set_link(db,aid,target,expected_profile_id=original);db.commit()
    assert profile_months(db,original)['months']==[]
    assert profile_months(db,target)['sent']==3
    set_link(db,aid,None,expected_profile_id=target);db.commit()
    assert profile_months(db,target)['months']==[]
    with source_engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM objects WHERE object_kind='chat_month'")).scalar_one()==1
        assert c.execute(text('SELECT count(*) FROM revisions')).scalar_one()==1
    start,end=message_month_bounds('2026-03','America/Chicago')
    assert start.astimezone(UTC).hour==6 and end.astimezone(UTC).hour==5
    with pytest.raises(HTTPException):message_month_bounds('2026-13','UTC')
    with pytest.raises(HTTPException):message_month_bounds('2026-03','bad_timezone')


def test_source_calls_money_keep_unknown_amount_and_follow_unlinked_account(db,source_engine,monkeypatch,tmp_path):
    import json

    from app.contact_events import import_archive, records, summary
    monkeypatch.setattr('app.contact_events.platform_engine',lambda _:source_engine)
    original,target=uuid4(),uuid4()
    for pid in (original,target):db.execute(text("INSERT INTO profiles(id,profile_type,display_name) VALUES(:id,'person','Same name')"),{'id':pid})
    db.execute(text("INSERT INTO identities(profile_id,provider,external_id) VALUES(:id,'wechat','wxid_event_owner')"),{'id':original})
    register_accounts(db,'wechat');aid=db.execute(text('SELECT id FROM source_accounts')).scalar_one()
    db.execute(text('UPDATE source_accounts SET migrated_at=now()'));db.execute(text("INSERT INTO platform_migration_state(provider,enabled) VALUES('wechat',true)"));db.commit()
    common={'provider':'wechat','snapshot_at':'2026-08-21 00:00:00','updated_at':'2026-08-21 00:00:00','occurred_at':1700000000}
    calls=[{**common,'id':i,'external_id':f'call-{i}','session_name':'wxid_event_owner','media_type':'voice','direction':'out',
        'media_type_confidence':'high' if i==1 else 'low','status':'completed' if i==1 else 'canceled','duration_seconds':123 if i==1 else None} for i in (1,2)]
    money=[{**common,'id':i,'external_id':f'money-{i}','context_id':'wxid_event_owner','kind':'red_packet' if i==3 else 'transfer',
        'amount_minor':None if i==3 else 100,'currency':'USD' if i==2 else 'CNY','direction':None if i==3 else 'in'} for i in (1,2,3)]
    path=tmp_path/'events.json';path.write_text(json.dumps({'call_interactions':calls,'money_interactions':money}))
    assert import_archive(db,path)['call']['projected_rows']==2
    replay=import_archive(db,path);assert replay['call']['changed_source_objects']==replay['money']['changed_source_objects']==0
    data=summary(db,original);assert data['calls']['total']==2 and data['calls']['duration_seconds']==123
    assert data['money']['currencies']=={'CNY':{'in':100,'out':0},'USD':{'in':100,'out':0}}
    assert data['money']['unknown_amount']==data['money']['unknown_direction']==1
    assert len(records(db,original,'call',0,1))==1 and len(records(db,original,'call',1,1))==1
    set_link(db,aid,None,expected_profile_id=original);db.commit();assert summary(db,original)['money']['total']==0
    set_link(db,aid,target,expected_profile_id=None);db.commit();assert summary(db,target)['money']['total']==3
    with source_engine.connect() as c:assert c.execute(text('SELECT count(*) FROM objects')).scalar_one()==5


def test_global_atlas_and_statistics_follow_links_across_worker_caches(db,source_engine):
    from app.location_atlas import _cache as locations_cache
    from app.location_atlas import atlas
    from app.social_analytics import _cache as stats_cache
    from app.social_analytics import social_analytics
    locations_cache.clear();stats_cache.clear()
    original,target=uuid4(),uuid4()
    for pid in (original,target):db.execute(text("INSERT INTO profiles(id,profile_type,display_name) VALUES(:id,'person','Atlas person')"),{'id':pid})
    db.execute(text("INSERT INTO identities(profile_id,provider,external_id) VALUES(:id,'linkedin','atlas-account')"),{'id':original})
    register_accounts(db,'linkedin');aid=db.execute(text('SELECT id FROM source_accounts')).scalar_one()
    db.execute(text('UPDATE source_accounts SET migrated_at=now()'))
    db.execute(text("INSERT INTO platform_migration_state(provider,enabled) VALUES('linkedin',true)"))
    project_batch(db,ImportBatchRequest(source='linkedin',stream='profiles',batch_id='atlas',idempotency_key='atlas',observed_at=datetime.now(UTC),
        records=[{'external_id':'atlas-account','profile_id':original,'content':{'fields':{'linkedin.location':'Pittsburgh, Pennsylvania, United States'}}}]))
    db.commit()
    first=atlas(db,provider='linkedin',kind='profile')
    assert first['people']==1 and first['points'][0]['people'][0]['id']==str(original)
    assert first['points'][0]['latitude']==pytest.approx(40.44062)
    assert social_analytics(db,original)['providers']['linkedin']['people']==1
    # A second process or an in-flight request can retain the previous cache
    # even after the linking process clears its own memory.
    old_locations=dict(locations_cache);old_stats=dict(stats_cache)
    set_link(db,aid,None,expected_profile_id=original);db.commit()
    locations_cache.update(old_locations);stats_cache.update(old_stats)
    assert atlas(db,provider='linkedin',kind='profile')['people']==0
    assert social_analytics(db,original)['providers']['linkedin']['people']==0
    set_link(db,aid,target,expected_profile_id=None);db.commit()
    moved=atlas(db,provider='linkedin',kind='profile')
    assert moved['people']==1 and moved['points'][0]['people'][0]['id']==str(target)
    with source_engine.connect() as c:assert c.execute(text("SELECT count(*) FROM objects WHERE object_kind='profile'")).scalar_one()==1
