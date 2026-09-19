"""Small social dashboards from metadata; never select message bodies."""
from collections import Counter
from datetime import UTC, datetime
from time import monotonic

from sqlalchemy import text

_cache={}


def social_analytics(db, profile_id=None):
    link_revision=db.execute(text('SELECT COALESCE(max(id),0) FROM source_account_link_revisions')).scalar_one()
    key=(str(profile_id or 'all'),link_revision)
    if key in _cache and monotonic()-_cache[key][0]<120:return _cache[key][1]
    params={'pid':str(profile_id) if profile_id else None}
    post_sql="""SELECT p.id,p.profile_id,p.provider,p.occurred_at,
        p.like_count likes,p.comment_count comments,
        EXISTS(SELECT 1 FROM media_links l WHERE l.entity_type='social_post' AND l.entity_id=p.id) ready
        FROM social_posts p
        WHERE (CAST(:pid AS uuid) IS NULL OR p.profile_id=CAST(:pid AS uuid))"""
    providers={p:{'posts':0,'likes':0,'comments':0,'authors':0,'local_photo_posts':0,'people':0,'monthly':[],'leaders':[],'charts':[]} for p in ('wechat','instagram','linkedin')}
    for row in db.execute(text(f"""WITH posts AS ({post_sql}) SELECT provider,count(*) posts,count(DISTINCT profile_id) authors,
        sum(likes) likes,sum(comments) comments,count(*) FILTER(WHERE ready) local_photo_posts,min(occurred_at) first,max(occurred_at) latest
        FROM posts GROUP BY provider"""),params).mappings():
        if row['provider'] in providers:providers[row['provider']].update(dict(row))
    for row in db.execute(text("""SELECT i.provider,count(DISTINCT i.profile_id) people FROM identities i JOIN profiles p ON p.id=i.profile_id
        WHERE i.status NOT IN ('invalid','merged') AND p.profile_type='person' AND p.archived_at IS NULL
        AND (CAST(:pid AS uuid) IS NULL OR p.id=CAST(:pid AS uuid)) GROUP BY i.provider"""),params).mappings():
        if row['provider'] in providers:providers[row['provider']]['people']=row['people']
    for row in db.execute(text("""SELECT provider,to_char(occurred_at AT TIME ZONE 'UTC','YYYY-MM') AS month,count(*) AS count
        FROM social_posts WHERE occurred_at IS NOT NULL AND (CAST(:pid AS uuid) IS NULL OR profile_id=CAST(:pid AS uuid))
        GROUP BY provider,month ORDER BY month"""),params).mappings():
        if row['provider'] in providers:providers[row['provider']]['monthly'].append(dict(row))
    for row in db.execute(text("""WITH totals AS MATERIALIZED (
        SELECT provider,profile_id,count(*) posts,sum(like_count+comment_count) value
        FROM social_posts WHERE profile_id IS NOT NULL
          AND (CAST(:pid AS uuid) IS NULL OR profile_id=CAST(:pid AS uuid))
        GROUP BY provider,profile_id), ranked AS (
        SELECT p.*,pr.display_name name,pr.avatar_media_id,
        row_number() OVER(PARTITION BY p.provider ORDER BY p.value DESC,p.posts DESC,p.profile_id) ranking
        FROM totals p JOIN profiles pr ON pr.id=p.profile_id WHERE pr.archived_at IS NULL)
        SELECT * FROM ranked WHERE ranking<=8 ORDER BY provider,ranking"""),params).mappings():
        if row['provider'] in providers:providers[row['provider']]['leaders'].append(dict(row))
    # Archived conversation summaries predate the current full message index;
    # their scope and date are explicit and they do not trigger message scans.
    direct=[];groups=[]
    for row in db.execute(text("""SELECT c.profile_id,p.display_name name,c.field_key,c.value
        FROM profile_metric_values c JOIN profiles p ON p.id=c.profile_id AND p.archived_at IS NULL
        WHERE c.field_key IN ('wechat.direct_stats','wechat.group_stats')
        AND (CAST(:pid AS uuid) IS NULL OR c.profile_id=CAST(:pid AS uuid))
        ORDER BY c.profile_id,c.field_key"""),params).mappings():
        value=row['value']
        if isinstance(value,dict):
            count=int(value.get('n',0) or 0)
            item={'profile_id':str(row['profile_id']),'name':row['name'],'value':count,'sent':value.get('sent',0),'received':value.get('recv',0),'last':value.get('last')}
            (direct if row['field_key']=='wechat.direct_stats' else groups).append(item)
    wechat=providers['wechat']
    wechat['chat']={'contacts':sum(x['value']>0 for x in direct),'messages':sum(x['value'] for x in direct),
                    'sent':sum(int(x['sent'] or 0) for x in direct),'received':sum(int(x['received'] or 0) for x in direct),
                    'leaders':sorted(direct,key=lambda x:-x['value'])[:8],'group_leaders':sorted(groups,key=lambda x:-x['value'])[:8]}
    distribution=Counter('无私聊' if x['value']==0 else '1–99 条' if x['value']<100 else '100–999 条' if x['value']<1000 else '1,000 条以上' for x in direct)
    wechat['charts'].append({'title':'私聊活跃度（归档摘要）','denominator':len(direct),'rows':[{'name':name,'count':distribution[name],'profile_id':next(x['profile_id'] for x in direct if ('无私聊' if x['value']==0 else '1–99 条' if x['value']<100 else '100–999 条' if x['value']<1000 else '1,000 条以上')==name)} for name in ('无私聊','1–99 条','100–999 条','1,000 条以上') if distribution[name]]})
    if not profile_id:
        wechat['groups']=db.execute(text("SELECT count(*) FROM profiles WHERE profile_type='group' AND archived_at IS NULL")).scalar_one()
        wechat['indexed_messages']=db.execute(text('SELECT COALESCE(sum(projected_count),0) FROM message_source_cursors')).scalar_one()
        wechat['conversations']=db.execute(text('SELECT count(*) FROM conversations')).scalar_one()
        for table,revision,fact,title in [('companies','profile_employment_revisions','employment','工作机构'),('schools','profile_education_revisions','education','教育经历')]:
            column='company_id' if fact=='employment' else 'school_id'
            rows=[dict(r) for r in db.execute(text(f"""SELECT e.name,count(DISTINCT c.profile_id) count,min(c.profile_id::text) profile_id
                FROM profile_structured_current c JOIN {revision} r ON r.id=c.current_revision_id JOIN {table} e ON e.id=r.{column}
                JOIN profiles p ON p.id=c.profile_id AND p.archived_at IS NULL
                WHERE c.fact_type=:fact AND c.current_source_type='linkedin' GROUP BY e.name ORDER BY count DESC,e.name LIMIT 6"""),{'fact':fact}).mappings()]
            providers['linkedin']['charts'].append({'title':title,'denominator':providers['linkedin']['people'],'rows':rows,'filter':'company' if fact=='employment' else 'school'})
        rows=[dict(r) for r in db.execute(text("""SELECT c.profile_id,p.display_name name,(c.value #>> '{}')::bigint count
            FROM profile_metric_values c JOIN profiles p ON p.id=c.profile_id AND p.archived_at IS NULL
            WHERE c.field_key ~ '^instagram.accounts.[^.]+.followers_count$' AND jsonb_typeof(c.value)='number'
            ORDER BY count DESC LIMIT 8""")).mappings()]
        providers['instagram']['charts'].append({'title':'粉丝数（采集时）','rows':rows,'denominator':providers['instagram']['people']})
    result={'providers':providers,'as_of':datetime.now(UTC).isoformat(),'scope':'已收录社交动态；私聊数据来自 Chatlog 归档摘要','profile_id':str(profile_id) if profile_id else None}
    if len(_cache)>256:_cache.clear()
    _cache[key]=(monotonic(),result)
    return result
