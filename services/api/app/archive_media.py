"""Link existing local social images by explicit archive IDs and Chatlog cache keys."""
import argparse
import hashlib
import json
import mimetypes
import os
import shutil
import sqlite3
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote_plus

from sqlalchemy import text

from .db import SessionLocal


def copy_media_snapshot(source, target):
    """Use a private CoW copy on NAS Btrfs; fall back to a normal atomic copy.

    Never hard-link a mutable collector cache into the content-addressed store.
    FICLONE changes remain private when either file is edited or removed.
    """
    fd, temporary = tempfile.mkstemp(prefix='.media-', dir=target.parent)
    try:
        with os.fdopen(fd, 'wb') as output, source.open('rb') as input_file:
            cloned = False
            if sys.platform == 'linux':
                import fcntl
                try:
                    fcntl.ioctl(output.fileno(), 0x40049409, input_file.fileno())  # Linux FICLONE
                    cloned = True
                except OSError:
                    output.seek(0)
                    output.truncate()
            if not cloned:
                shutil.copyfileobj(input_file, output, 1024 * 1024)
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)


def register_file(db, path, media_root, provider):
    path=Path(path).resolve();stamp=path.stat()
    media_root=Path(media_root).resolve()
    cached=db.execute(text('''SELECT f.media_id,a.object_path FROM archive_media_files f
        JOIN media_assets a ON a.id=f.media_id WHERE f.provider=:provider AND f.source_path=:path
          AND f.byte_length=:bytes AND f.modified_ns=:modified'''),
        {'provider':provider,'path':str(path),'bytes':stamp.st_size,'modified':stamp.st_mtime_ns}).mappings().one_or_none()
    if cached and Path(cached['object_path']).is_file():return cached['media_id']
    media_root.mkdir(parents=True,exist_ok=True)
    fd,temporary=tempfile.mkstemp(prefix='.archive-',dir=media_root);os.close(fd)
    snapshot=Path(temporary)
    try:
        # Hash the private snapshot, not a file the collector can overwrite
        # between hashing and copying. CoW avoids another physical NAS copy.
        copy_media_snapshot(path,snapshot)
        current=path.stat()
        if (stamp.st_size,stamp.st_mtime_ns)!=(current.st_size,current.st_mtime_ns):
            raise OSError('Collector media changed during snapshot; retry the archive scan')
        digest=hashlib.sha256()
        with snapshot.open('rb') as stream:
            head=stream.read(32);digest.update(head)
            while chunk:=stream.read(1024*1024):digest.update(chunk)
        mime=mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
        if head.startswith(b'\xff\xd8\xff'):mime='image/jpeg'
        elif head.startswith(b'\x89PNG'):mime='image/png'
        elif head.startswith(b'GIF8'):mime='image/gif'
        elif head[8:12]==b'WEBP':mime='image/webp'
        elif head[4:8]==b'ftyp':mime='video/mp4'
        if not mime.startswith(('image/','video/')):return None
        sha=digest.hexdigest()
        target=media_root/'sha256'/sha[:2]/sha[2:4]/sha
        target.parent.mkdir(parents=True,exist_ok=True)
        if not target.exists():os.replace(snapshot,target)
    finally:snapshot.unlink(missing_ok=True)
    existing=db.execute(text('SELECT id FROM media_assets WHERE sha256=:sha'),{'sha':sha}).scalar_one_or_none()
    if existing:
        db.execute(text('UPDATE media_assets SET object_path=:path WHERE id=:id AND object_path IS DISTINCT FROM :path'), {'path':str(target.resolve()),'id':existing})
        media=existing
    else:
        content=db.execute(text("""INSERT INTO content_objects(sha256,content_kind,byte_length,storage_uri)
            VALUES (:sha,'media',:size,:path) ON CONFLICT(content_kind,sha256) DO UPDATE SET storage_uri=EXCLUDED.storage_uri RETURNING id"""),
            {'sha':sha,'size':stamp.st_size,'path':str(target)}).scalar_one()
        media=db.execute(text("""INSERT INTO media_assets(sha256,content_object_id,media_type,byte_length,object_path,source_type,source_record_id)
            VALUES (:sha,:content,:mime,:size,:target,:provider,:source) ON CONFLICT(sha256) DO UPDATE SET object_path=EXCLUDED.object_path RETURNING id"""),
            {'sha':sha,'content':content,'mime':mime,'size':stamp.st_size,'target':str(target),'provider':provider,'source':str(path)}).scalar_one()
    db.execute(text('''INSERT INTO archive_media_files(provider,source_path,byte_length,modified_ns,media_id)
        VALUES(:provider,:path,:bytes,:modified,:media) ON CONFLICT(provider,source_path) DO UPDATE SET
        byte_length=EXCLUDED.byte_length,modified_ns=EXCLUDED.modified_ns,media_id=EXCLUDED.media_id'''),
        {'provider':provider,'path':str(path),'bytes':stamp.st_size,'modified':stamp.st_mtime_ns,'media':media})
    return media


def fix_url(url,token,video=False):
    url=url.replace('http://','https://',1)
    if not video:
        url=url.replace('/150?','/0?')
        if url.endswith('/150'):url=url[:-4]+'/0'
    if not token or 'token=' in url:return url
    if video:
        parts=url.split('?',1)
        return parts[0]+'?token='+quote_plus(token)+'&idx=1'+('&'+parts[1] if len(parts)>1 else '')
    return url+('&' if '?' in url else '?')+'token='+quote_plus(token)+'&idx=1'


def link(db,media_id,entity_id,role,provider_url=None,entity_type='social_post',retain=True):
    if not media_id:return
    if provider_url:
        db.execute(text("""INSERT INTO remote_media_sources(source_url,media_id) VALUES (:url,:media)
            ON CONFLICT(source_url) DO UPDATE SET media_id=EXCLUDED.media_id
            WHERE remote_media_sources.media_id IS DISTINCT FROM EXCLUDED.media_id"""),{'url':provider_url,'media':media_id})
        # Upgrading a cached thumbnail to its original changes this one slot.
        # Prior bytes and the URL's true A→B→A history remain archived.
        db.execute(text('''DELETE FROM media_links l USING media_source_revisions r
            WHERE r.source_url=:url AND l.media_id=r.media_id AND l.media_id<>:media
              AND l.entity_type=:type AND l.entity_id=:entity AND l.role=:role'''),
            {'url':provider_url,'media':media_id,'type':entity_type,'entity':entity_id,'role':role})
    added=db.execute(text("""INSERT INTO media_links(media_id,entity_type,entity_id,role)
        VALUES (:media,:type,:entity,:role) ON CONFLICT DO NOTHING"""),
        {'media':media_id,'type':entity_type,'entity':entity_id,'role':role}).rowcount
    if retain:
        from .remote_media import retain_source_media
        retain_source_media(db,{'entity_type':entity_type,'entity_id':entity_id,'role':role},media_id)
    return added


def moments_cache(db, sqlite_path, cache, media_root, limit=0, audit=False):
    from .remote_media import retain_post_media_batch

    posts=dict(db.execute(text("SELECT external_id,id FROM social_posts WHERE provider='wechat'")).all())
    # One directory inventory avoids hundreds of thousands of remote stat
    # calls. A newly downloaded cache file is picked up on the next scan.
    available={p.name for p in cache.iterdir() if p.name.endswith('.bin')} if cache.is_dir() else set()
    result={'source_posts':0,'source_media':0,'cache_directory_available':cache.is_dir(),'cache_files':len(available),'cache_matches':0,
        'linked_media':0,'added_links':0,'unavailable_media':0,'unsupported_files':0,'unmapped_posts':0,'invalid_xml':0}
    pending=[]
    def commit_media():
        if pending:
            retain_post_media_batch(db,pending)
            db.commit();pending.clear()
    with sqlite3.connect(f'file:{sqlite_path}?mode=ro',uri=True) as source:
        for index,(tid,xml) in enumerate(source.execute('SELECT tid,content FROM SnsTimeLine')):
            if limit and index>=limit:break
            result['source_posts']+=1
            try:root=ET.fromstring(xml or '')
            except ET.ParseError:result['invalid_xml']+=1;continue
            obj=root.find('TimelineObject')
            if obj is None:result['invalid_xml']+=1;continue
            post=posts.get(obj.findtext('id') or str(tid))
            if not post:result['unmapped_posts']+=1;continue
            for position,media in enumerate(obj.findall('ContentObject/mediaList/media')):
                result['source_media']+=1
                url=media.find('url');thumb=media.find('thumb')
                attrs={**(thumb.attrib if thumb is not None else {}),**(url.attrib if url is not None else {})}
                key=attrs.get('key','');token=attrs.get('token','');is_video=media.findtext('type') in ('6','15')
                if not key or key=='0':
                    enc=root.find('.//enc');key=enc.get('key','') if enc is not None else key
                found=None;original=media.findtext('url') or media.findtext('thumb')
                for raw,video in [(media.findtext('url'),is_video),(media.findtext('thumb'),False)]:
                    if not raw:continue
                    for candidate in [fix_url(raw,token,video),raw]:
                        path=cache/(hashlib.md5((candidate+'|'+key).encode()).hexdigest()+'.bin')
                        if path.name in available:found=path;break
                    if found:break
                if found:
                    result['cache_matches']+=1
                    if not audit:
                        asset=register_file(db,found,media_root,'wechat')
                        if asset:
                            role=f'media-{position+1}'
                            result['added_links']+=link(db,asset,post,role,original,retain=False)
                            pending.append({'post':str(post),'media':str(asset),'role':role})
                            result['linked_media']+=1
                        else:result['unsupported_files']+=1
                        # Short, bounded transactions retain source and CRM
                        # pointers without a separate disk commit per image.
                        if len(pending)>=25:commit_media()
                else:result['unavailable_media']+=1
            if index%400==0:
                commit_media()
                db.commit();print(json.dumps({'posts_checked':index,**result}),flush=True)
    commit_media()
    db.commit();return result


def instagram_archive(db,root,media_root):
    posts=dict(db.execute(text("SELECT external_id,id FROM social_posts WHERE provider='instagram'")).all())
    from .source_projection import enabled
    source_enabled=enabled(db,'instagram')
    aliases={}
    if source_enabled:
        from .platform_migrate import account_lookup
        _,aliases,_=account_lookup(db,'instagram')
    identities=dict(db.execute(text("SELECT external_id,profile_id FROM identities WHERE provider='instagram' AND status NOT IN ('invalid','merged')")).all())
    result={'posts_with_files':0,'linked_media':0,'avatars':0}
    for directory in root.iterdir():
        if not directory.is_dir():continue
        account=aliases.get('username:'+directory.name) or aliases.get(directory.name)
        profile=None if source_enabled else identities.get('username:'+directory.name) or identities.get(directory.name)
        for path in directory.glob('*.json'):
            if '_UTC_' not in path.name:continue
            try:payload=json.loads(path.read_text());node=payload.get('node',payload)
            except (ValueError,OSError):continue
            shortcode=str(node.get('shortcode') or '')
            post=posts.get(str(node.get('id'))) or posts.get(shortcode)
            if not post:continue
            files=sorted(p for p in directory.glob(path.stem+'*') if p.suffix.lower() in ('.jpg','.jpeg','.png','.webp','.mp4'))
            result['posts_with_files']+=bool(files)
            for index,file in enumerate(files):
                asset=register_file(db,file,media_root,'instagram');link(db,asset,post,f'media-{index+1}')
                result['linked_media']+=bool(asset)
        if account or profile:
            for file in directory.glob('*profile_pic*'):
                if file.suffix.lower() not in ('.jpg','.jpeg','.png'):continue
                asset=register_file(db,file,media_root,'instagram');link(db,asset,account or profile,'instagram_avatar',entity_type='source_account' if account else 'profile')
                if asset:
                    if profile:db.execute(text('UPDATE profiles SET avatar_media_id=COALESCE(avatar_media_id,:asset) WHERE id=:id'),{'id':profile,'asset':asset})
                    result['avatars']+=1
        db.commit()
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--sns-db',type=Path);parser.add_argument('--cache',type=Path);parser.add_argument('--instagram-root',type=Path);parser.add_argument('--media-root',type=Path,default=Path('/data/media'));parser.add_argument('--limit',type=int,default=0);parser.add_argument('--audit',action='store_true');args=parser.parse_args()
    if args.audit and args.instagram_root:parser.error('--audit currently supports only the Chatlog cache')
    with SessionLocal() as db:
        if args.sns_db:print(json.dumps(moments_cache(db,args.sns_db,args.cache,args.media_root,args.limit,args.audit)),flush=True)
        if args.instagram_root:print(json.dumps(instagram_archive(db,args.instagram_root,args.media_root)),flush=True)


if __name__=='__main__':main()
