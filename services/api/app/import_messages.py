"""Append missing Chatlog messages in bounded transactions, with per-table cursors.

Stable talker IDs come from Name2Id/MD5 table keys. No name-based joins. Source
SQLite remains the original archive; normalized content is stored once by hash.
"""
import argparse
import base64
import hashlib
import json
import re
import sqlite3
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import text

from .content import canonical_json
from .db import SessionLocal, engine


def decode(value):
    if isinstance(value,bytes):
        if value.startswith(b'\x28\xb5\x2f\xfd'):
            import zstandard
            value=zstandard.ZstdDecompressor().decompress(value,max_output_size=32*1024*1024)
        try:return value.decode('utf-8').replace('\x00','')
        except UnicodeDecodeError:return None
    return str(value or '').replace('\x00','')


def search_text(value):
    """Index human message text; the complete original stays in content_objects.

    WeChat media XML includes long signatures and binary keys. Indexing those
    as trigrams creates enormous write amplification without searchable words.
    """
    if not value:return ''
    candidate=re.sub(r'^[^<\n]{1,100}:\n(?=<)', '', value).strip()
    if not candidate.startswith('<'):return value
    try:root=ET.fromstring(candidate)
    except ET.ParseError:return value
    labels={'title','des','description','content','text','displayname','nickname','pay_memo','memo','appname','recorddesc'}
    words=[]
    for node in root.iter():
        if node.tag.lower() in labels and node.text and node.text.strip():words.append(node.text.strip())
    return '\n'.join(dict.fromkeys(words))


def ingest(db,root,profile=None,limit=0):
    people={r.external_id:str(r.profile_id) for r in db.execute(text("SELECT external_id,profile_id FROM identities WHERE provider IN ('wechat','wechat_group') AND profile_id IS NOT NULL AND status NOT IN ('invalid','merged')"))}
    from .source_projection import enabled
    independent=enabled(db,'wechat');accounts={}
    if independent:
        from .platform_migrate import account_lookup
        _,accounts,_profiles=account_lookup(db,'wechat')
        from .platform_store import ensure_account, observe_many, platform_engine
    report={'source_rows':0,'inserted':0,'unmapped_tables':0,'invalid_dates':0,'binary_bodies':0,'tables':0}
    partitions=set(db.execute(text("SELECT tablename FROM pg_tables WHERE schemaname=current_schema() AND tablename LIKE 'message_events_%'")).scalars())
    # Reuse one staging table. Recreating/dropping it for every conversation
    # bloats PostgreSQL's catalogs and competes with browsing on NAS disks.
    db.execute(text("""CREATE TEMP TABLE IF NOT EXISTS message_input (
        conversation uuid,sender uuid,at timestamptz,type text,record text,
        payload jsonb,digest char(64),length bigint,body text,sender_account uuid) ON COMMIT DELETE ROWS"""))
    db.commit()
    for path in sorted(root.glob('message_[0-9]*.db')):
        with sqlite3.connect(f'file:{path}?mode=ro',uri=True) as source:
            names={r[0]:r[1] for r in source.execute('SELECT rowid,user_name FROM Name2Id') if r[1]}
            talkers={hashlib.md5(n.encode()).hexdigest():n for n in set(names.values())|set(people)}
            tables=[r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'")]
            for table in tables:
                if not re.fullmatch('Msg_[0-9a-fA-F]{32}',table):continue
                talker=talkers.get(table[4:]);pid=people.get(talker)
                if profile and pid!=profile:continue
                if not talker:
                    report['unmapped_tables']+=1;continue
                kind='group' if talker.endswith('@chatroom') else 'direct'
                aid=accounts.get(talker)
                if independent:
                    db.execute(text('SELECT pg_advisory_xact_lock_shared(11803295)'))
                    if not aid:
                        with platform_engine('wechat').begin() as platform:
                            aid=ensure_account(platform,'wechat',talker,kind='group' if kind=='group' else 'person')
                        db.execute(text("""INSERT INTO source_accounts(id,provider,external_id,object_kind,display_name,migrated_at)
                            VALUES(:id,'wechat',:ext,:kind,:ext,now()) ON CONFLICT DO NOTHING"""),{'id':aid,'ext':talker,'kind':'group' if kind=='group' else 'person'})
                        accounts[talker]=str(aid)
                    db.execute(text('SELECT id FROM source_accounts WHERE id=:id FOR UPDATE'),{'id':aid})
                    pid=db.execute(text('SELECT profile_id FROM source_account_links WHERE account_id=:id'),{'id':aid}).scalar_one_or_none()
                conversation=db.execute(text("""INSERT INTO conversations(conversation_type,profile_id,external_id,source_account_id)
                    VALUES(:kind,:pid,:ext,:account) ON CONFLICT(conversation_type,external_id) DO UPDATE SET
                    profile_id=CASE WHEN :independent THEN EXCLUDED.profile_id ELSE COALESCE(EXCLUDED.profile_id,conversations.profile_id) END,
                    source_account_id=COALESCE(EXCLUDED.source_account_id,conversations.source_account_id) RETURNING id"""),
                    {'kind':kind,'pid':pid,'ext':kind+':'+talker,'account':aid,'independent':independent}).scalar_one()
                count=source.execute(f'SELECT count(*) FROM {table}').fetchone()[0];report['source_rows']+=count;report['tables']+=1
                last=db.execute(text('SELECT last_local_id FROM message_source_cursors WHERE source_file=:file AND source_table=:table'),{'file':path.name,'table':table}).scalar_one_or_none() or 0
                cursor=source.execute(f'SELECT local_id,server_id,create_time,local_type,real_sender_id,message_content,compress_content FROM {table} WHERE local_id>? ORDER BY local_id',(last,))
                while rows:=cursor.fetchmany(2000):
                    normalized=[]
                    for local_id,server_id,epoch,typ,sender,body,compressed in rows:
                        try:at=datetime.fromtimestamp(epoch,UTC)
                        except (TypeError,ValueError,OSError):report['invalid_dates']+=1;continue
                        if at.year<1990 or at.year>2100:report['invalid_dates']+=1;continue
                        value=decode(body) or decode(compressed)
                        if value is None:report['binary_bodies']+=1
                        content={'text':value or '', 'sender_external_id':names.get(sender),'message_type':typ}
                        if value is None and isinstance(body,bytes):content['binary_base64']=base64.b64encode(body).decode()
                        encoded=canonical_json(content);digest=hashlib.sha256(encoded).hexdigest()
                        record=f'server:{server_id}' if server_id else f'{path.name}:{table}:{local_id}'
                        normalized.append({'conversation':str(conversation),'sender':people.get(names.get(sender)), 'at':at.isoformat(),
                            'type':str(typ),'record':record,'payload':json.loads(encoded),'digest':digest,'length':len(encoded),'body':search_text(value),
                            'sender_account':accounts.get(names.get(sender))})
                    if normalized:
                        if independent:
                            db.execute(text('SELECT pg_advisory_xact_lock_shared(11803295)'))
                            # Lock linkage per bounded transaction. A concurrent unlink
                            # waits for this projection, then changes only CRM indexes.
                            db.execute(text('SELECT id FROM source_accounts WHERE id=:id FOR UPDATE'),{'id':aid})
                            with platform_engine('wechat').begin() as platform:
                                observe_many(platform,[{'account':aid,'kind':'message','external_id':r['record']+':'+r['at'],
                                    'value':r['payload'],'occurred_at':datetime.fromisoformat(r['at']),
                                    'source_event':'chatlog:'+path.name+':'+table+':'+r['record']} for r in normalized])
                        missing_months=[]
                        for month in {r['at'][:7] for r in normalized}:
                            year,m=map(int,month.split('-'));table_name=f'message_events_{year}_{m:02}'
                            if table_name not in partitions:missing_months.append((month,year,m,table_name))
                        if missing_months:
                            # DDL takes parent-table/FK locks. Never request it
                            # while this batch holds content/profile write locks.
                            db.commit()
                            for month,year,m,table_name in missing_months:
                                next_month=f'{year+1}-01-01' if m==12 else f'{year}-{m+1:02}-01'
                                db.execute(text(f"CREATE TABLE IF NOT EXISTS {table_name} PARTITION OF message_events FOR VALUES FROM ('{month}-01') TO ('{next_month}')"))
                                db.commit();partitions.add(table_name)
                        db.execute(text("""INSERT INTO message_input SELECT * FROM jsonb_to_recordset(CAST(:rows AS jsonb))
                          AS r(conversation uuid,sender uuid,at timestamptz,type text,record text,payload jsonb,digest char(64),length bigint,body text,sender_account uuid)"""),{'rows':json.dumps(normalized,ensure_ascii=False)})
                        # Match the durable CHAR(64) hash type and give the planner
                        # batch statistics; TEXT casts defeat the content index.
                        db.execute(text('ANALYZE message_input'))
                        db.execute(text("""INSERT INTO content_objects(sha256,content_kind,byte_length,payload_json)
                            SELECT DISTINCT ON(digest) digest,'message',length,payload FROM message_input ON CONFLICT(content_kind,sha256) DO NOTHING"""))
                        inserted=db.execute(text("""WITH inserted AS (
                            INSERT INTO message_events(conversation_id,sender_profile_id,occurred_at,message_type,content_object_id,source_record_id,sender_account_id)
                            SELECT i.conversation,CASE WHEN :independent THEN l.profile_id ELSE i.sender END,i.at,i.type,c.id,i.record,i.sender_account FROM message_input i
                            JOIN content_objects c ON c.sha256=i.digest AND c.content_kind='message'
                            LEFT JOIN source_account_links l ON l.account_id=i.sender_account
                            ON CONFLICT(conversation_id,source_record_id,occurred_at) DO NOTHING
                            RETURNING id,occurred_at,conversation_id,source_record_id
                        ), indexed AS (
                            INSERT INTO message_search(message_id,occurred_at,conversation_id,body)
                            SELECT m.id,m.occurred_at,m.conversation_id,i.body FROM message_input i JOIN inserted m
                            ON m.conversation_id=i.conversation AND m.source_record_id=i.record AND m.occurred_at=i.at
                            ON CONFLICT(message_id,occurred_at) DO NOTHING
                        ) SELECT count(*) FROM inserted"""),{'independent':independent}).scalar_one()
                        report['inserted']+=inserted
                    db.execute(text("""INSERT INTO message_source_cursors(source_file,source_table,last_local_id,source_count,projected_count)
                        VALUES(:file,:table,:last,:count,:inserted) ON CONFLICT(source_file,source_table) DO UPDATE SET
                        last_local_id=EXCLUDED.last_local_id,source_count=EXCLUDED.source_count,
                        projected_count=message_source_cursors.projected_count+EXCLUDED.projected_count,updated_at=now()"""),
                        {'file':path.name,'table':table,'last':rows[-1][0],'count':count,'inserted':inserted if normalized else 0})
                    db.commit()
                    if limit and report['inserted']>=limit:return report
                db.commit()
        print(json.dumps({'file':path.name,**report}),flush=True)
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True);p.add_argument('--profile');p.add_argument('--limit',type=int,default=0);args=p.parse_args()
    with engine.connect() as lease:
        acquired=lease.execute(text('SELECT pg_try_advisory_lock(11803292)')).scalar_one();lease.commit()
        if not acquired:raise SystemExit('A message importer is already running for this database')
        try:
            with SessionLocal() as db:print(json.dumps(ingest(db,args.root,args.profile,args.limit)),flush=True)
        finally:
            lease.execute(text('SELECT pg_advisory_unlock(11803292)'));lease.commit()


if __name__=='__main__':main()
