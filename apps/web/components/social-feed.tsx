"use client";

import Link from "next/link";
import {useSearchParams} from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Heart, MessageCircle, X, ImageIcon, ArrowUpRight } from "lucide-react";
import {LoadMore} from "./load-more";
import {recordText} from "../lib/record-text";

type Media = { id?: string; source_url?: string; thumbnail_url?: string; media_type?: string };
type Event = { id: string; profile_id?: string; profile_name?: string; avatar_media_id?: string; provider: string; title: string; occurred_at?: string; summary?: string; cursor: string; media: Media[]; like_count?: number; comment_count?: number };
type Detail = { content?: unknown; summary?: string; participants?:{id:string;display_name:string}[]; media?: Media[]; interactions?: { id: string; interaction_type: string; author_name?: string; author_profile_id?: string; content?: { text?: string } }[] };
const labels: Record<string, string> = { all: "All", wechat: "WeChat", instagram: "Instagram", linkedin: "LinkedIn", manual: "Notes" };
const source = (media: Media) => media.id ? `/api/v1/media/${media.id}` : undefined;
const date = (value?: string) => value ? new Intl.DateTimeFormat("en-US", { dateStyle: "medium" }).format(new Date(value)) : "No date";

export function SocialFeed({ profileId, preview = false }: { profileId?: string; preview?: boolean }) {
  const search=useSearchParams();
  const [provider, setProvider] = useState(search.get("provider")||"all");
  const month=search.get("month");
  useEffect(()=>{setProvider(search.get("provider")||"all");},[search]);
  const [events, setEvents] = useState<Event[]>([]);
  const [loading, setLoading] = useState(false);
  const [more, setMore] = useState(false);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<Event | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [detailError, setDetailError] = useState("");
  const dialog = useRef<HTMLDialogElement>(null);
  const requestVersion = useRef(0);
  const request = useRef<AbortController|null>(null);
  const loadingPage = useRef(false);
  async function load(cursor?: string) {
    if(cursor&&loadingPage.current)return;
    request.current?.abort();const abort=new AbortController();request.current=abort;
    const version = ++requestVersion.current;loadingPage.current=true;
    setLoading(true); setError("");
    const pageSize = preview ? 6 : 18;
    const params = new URLSearchParams({ limit: String(pageSize) });
    if (profileId) params.set("profile_id", profileId);
    if (provider !== "all") params.set("provider", provider);
    if (cursor) params.set("cursor", cursor);
    if(month&&/^\d{4}-\d{2}$/.test(month)){const start=new Date(`${month}-01T00:00:00Z`);const end=new Date(start);end.setUTCMonth(end.getUTCMonth()+1);params.set("after",start.toISOString());params.set("before",end.toISOString());}
    try {
      const response = await fetch(`/api/v1/timeline?${params}`,{signal:abort.signal});
      if (!response.ok) throw new Error();
      const rows: Event[] = await response.json();
      if (version !== requestVersion.current) return;
      setEvents(previous => cursor ? [...previous, ...rows.filter(row=>!previous.some(old=>old.id===row.id))] : rows); setMore(rows.length === pageSize);
      const eventId = new URLSearchParams(window.location.search).get('event');
      const target = rows.find(row => row.id === eventId);
      if (target) setSelected(target);
      else if (eventId && !cursor) {
        const detailResponse=await fetch(`/api/v1/timeline/${encodeURIComponent(eventId)}`);
        if(detailResponse.ok && version===requestVersion.current){
          const event=await detailResponse.json();
          setSelected({...event,profile_name:event.profile_display_name,media:event.media || []});
        }
      }
    } catch { if (!abort.signal.aborted && version === requestVersion.current) setError("Could not load the timeline. Try again."); }
    finally { if (version === requestVersion.current) {loadingPage.current=false;setLoading(false);} }
  }
  useEffect(() => { setEvents([]);setMore(false);void load();return()=>{request.current?.abort();requestVersion.current++;loadingPage.current=false;}; }, [provider, profileId, month]);
  useEffect(() => {
    if (!selected) return;
    const abort = new AbortController();
    setDetail(null); setDetailError(""); dialog.current?.showModal();
    fetch(`/api/v1/timeline/${selected.id}`, { signal: abort.signal }).then(async response => {
      if (!response.ok) throw new Error(); setDetail(await response.json());
    }).catch(error => { if (error.name !== "AbortError") setDetailError("Could not load this post. Close and try again."); });
    return () => abort.abort();
  }, [selected]);
  return <section className="social-feed" id="timeline">
    <div className="feed-heading"><h2>{profileId ? "Updates and photos" : "What people posted"}</h2><div className="provider-tabs" aria-label="Timeline source">{Object.entries(labels).map(([key,label]) => <button type="button" key={key} aria-pressed={provider === key} className={provider === key ? "selected" : ""} onClick={() => setProvider(key)}>{label}</button>)}</div></div>
    {month&&<p className="analytics-scope">Posts in {month} <Link href={profileId?`/profiles/${profileId}?tab=timeline&provider=${provider}`:"/dashboard"}>Clear month</Link></p>}
    {error && <p role="alert">{error} <button className="button button-soft" onClick={() => void load(events.at(-1)?.cursor)}>Retry</button></p>}
    <div className="photo-feed">{events.map(event => <article className={`photo-story ${event.media?.length ? "with-photo" : "text-story"}`} key={event.id}>
      <header>{event.profile_id ? <Link className="story-person" href={`/profiles/${event.profile_id}`}>{event.avatar_media_id ? <img width={36} height={36} src={`/api/v1/media/${event.avatar_media_id}`} alt="" loading="lazy"/> : <span className="story-initial">{event.profile_name?.slice(0,1) || "P"}</span>}<strong>{event.profile_name || "Open person"}</strong></Link> : <strong>{event.title}</strong>}<span className={`provider-mark ${event.provider}`}>{labels[event.provider] || event.provider}</span></header>
      {event.media?.length > 0 && <button type="button" className="story-photo" onClick={() => setSelected(event)} aria-label={`Open ${event.title} from ${event.profile_name || "this person"}`}><FeedImage media={event.media[0]} alt={event.summary?.slice(0,80) || event.title}/>{event.media.length > 1 && <span className="photo-count"><ImageIcon size={13}/>{event.media.length}</span>}</button>}
      <button type="button" className="story-caption" onClick={() => setSelected(event)}><p>{humanSummary(event.summary) || event.title}</p><span>Open post <ArrowUpRight size={13}/></span></button>
      <footer><time>{date(event.occurred_at)}</time><span><Heart size={14}/>{event.like_count || 0}</span><span><MessageCircle size={14}/>{event.comment_count || 0}</span></footer>
    </article>)}</div>
    {loading && <p className="data-loading" role="status">Loading posts…</p>}
    {!loading && !events.length && !error && <p className="feed-empty">No imported posts for this source.</p>}
    {more && (preview ? <Link className="button button-soft feed-more" href={`/profiles/${profileId}?tab=timeline`}>See all posts</Link> : <LoadMore cursor={events.at(-1)?.cursor||""} busy={loading} error={!!error} onLoad={()=>void load(events.at(-1)?.cursor)}/>)}
    <dialog className="photo-dialog" ref={dialog} onClose={() => setSelected(null)} onClick={e => { if (e.target === e.currentTarget) dialog.current?.close(); }} aria-label="Post">
      <button className="dialog-close" type="button" aria-label="Close post" onClick={() => dialog.current?.close()}><X size={22}/></button>
      {selected && <><header><h2>{selected.profile_name || selected.title}</h2><p>{labels[selected.provider]} · {date(selected.occurred_at)}</p></header>
      <div className="dialog-photos">{(detail?.media || selected.media || []).map((media,index) => <a href={source(media)} target="_blank" rel="noreferrer" aria-label={`Original media ${index+1}`} key={media.id || media.source_url || index}>{media.media_type?.includes("video") ? <video controls preload="metadata" src={source(media)}/> : <FeedImage media={media} original alt={`Post photo ${index+1}`}/>}</a>)}</div>
      <p className="event-body">{recordText(detail?.content) || humanSummary(detail?.summary || selected.summary)}</p>
      {!!detail?.participants?.length&&<div className="record-people">{detail.participants.map(p=><Link key={p.id} href={`/profiles/${p.id}`}>{p.display_name}</Link>)}</div>}
      {!detail && !detailError && <p role="status">Loading interactions…</p>}{detailError && <p role="alert">{detailError}</p>}
      {!!detail?.interactions?.length && <section className="social-replies"><h3>Likes and comments</h3>{detail.interactions.map(item => <div key={item.id}>{item.interaction_type === "like" ? <Heart size={14}/> : <MessageCircle size={14}/>} {item.author_profile_id ? <Link href={`/profiles/${item.author_profile_id}`}>{item.author_name || "Open person"}</Link> : <strong>{item.author_name || "Person"}</strong>}<span>{item.content?.text}</span></div>)}</section>}</>}
    </dialog>
  </section>;
}
function FeedImage({ media, alt, original=false }: { media: Media; alt: string; original?:boolean }) {
  const [failed, setFailed] = useState(false);
  return failed || !source(media) ? <span className="photo-unavailable"><ImageIcon size={28}/>Photo unavailable</span> : <img src={media.id ? `/api/v1/media/${media.id}${original?"":"?variant=thumb"}` : source(media)} width={640} height={480} alt={alt} loading="lazy" onError={() => setFailed(true)}/>;
}
function humanSummary(value?: string): string {
  return recordText(value);
}
