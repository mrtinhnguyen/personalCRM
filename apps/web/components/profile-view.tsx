"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import {
  ArrowLeft,
  BriefcaseBusiness,
  ChevronRight,
  Clock3,
  Edit3,
  ExternalLink,
  GraduationCap,
  History,
  Heart,
  Images,
  Instagram,
  Link2,
  Linkedin,
  MapPin,
  MapPinned,
  MessageCircle,
  MessageSquare,
  Plus,
  Save,
  ShieldCheck,
  Tags,
  Users,
  UsersRound,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { apiFetch } from "../lib/api";

type Field = { field_key: string; value: unknown; current_source_type: string; updated_at: string; current_content_hash?: string | null };
type Identity = { id: string; provider: string; external_id: string; username?: string | null; profile_url?: string | null; display_name?: string | null; status?: string | null; first_seen_at?: string | null; last_seen_at?: string | null };
type StructuredFact = { fact_type: "address" | "employment" | "education"; value: unknown; current_source_type: string; updated_at: string; company_name?: string | null; school_name?: string | null };
type GroupLink = { group_profile_id: string; person_profile_id: string; display_name: string; profile_type: "person" | "group"; avatar_media_id?: string | null; role?: string | null; joined_at?: string | null; left_at?: string | null; observed_at?: string | null; source_record_id?: string | null };
type Observation = { id: string; source: string; stream: string; external_id: string; batch_id: string; source_cursor?: string | null; content_hash: string; observed_at: string; state: string; source_updated_at?: string | null };
type Presentation = {instagram_accounts?:Record<string,unknown>[];sources:Record<string,Record<string,unknown>>;facts:StructuredFact[]};
type Profile = {platform_avatars?:{provider:string;media_id:string;source_account_id?:string}[]; tags?:{id:string;name:string;source_type:string}[]; group_summary?:{messages:number;active_senders:number;first?:string;last?:string}; presentation?:Presentation; id: string; profile_type: "person" | "group"; display_name: string; summary?: string | null; avatar_media_id?: string | null; avatar_url?: string | null; linkedin_avatar_media_id?: string | null; cover_media_id?: string | null; cover_url?: string | null; fields?: Field[]; identities?: Identity[]; structured_facts?: StructuredFact[]; group_members?: GroupLink[]; group_owners?: GroupLink[]; member_of_groups?: GroupLink[]; group_member_count?: number; linked_group_count?: number; source_observations?: Observation[] };
type Revision = { id: string; field_key: string; value: unknown; source_type: string; operation: string; observed_at: string; is_conflict: boolean };
type TimelineMedia = { id?: string; media_type?: string | null; width?: number | null; height?: number | null; source_url?: string | null; thumbnail_url?: string | null; description?: string | null };
type TimelineItem = { id: string; provider: string; external_id: string; occurred_at?: string | null; title: string; summary?: string | null; content_hash?: string | null; media_count?: number; like_count?: number; comment_count?: number; location?: Record<string, unknown> | null; media?: TimelineMedia[] | null };
type TimelineInteraction = { id: string; interaction_type: string; external_id: string; author_profile_id?: string | null; author_external_id?: string | null; author_name?: string | null; occurred_at?: string | null; metadata?: Record<string, unknown> | null; content?: unknown };
type TimelineDetail = { event_type: string; id: string; provider: string; external_id: string; occurred_at?: string | null; title?: string | null; summary?: string | null; content?: unknown; profile_display_name?: string | null; content_hash?: string | null; coverage_status?: string | null; source_record_id?: string | null; media?: TimelineMedia[]; interactions?: TimelineInteraction[]; revisions?: { content_hash: string; observed_at: string; source_record_id?: string | null }[]; participants?: { id: string; display_name: string; profile_type: string }[] };
type ProfileMetric = { metric_key: string; value: unknown; freshness_state?: string | null };
type TimelineSummary = { providers: Record<string, { posts: number; stories: number; events: number; media: number; likes: number; comments: number; latest?: string | null }>; total_events: number };
type LocationSummary = { place_count: number; total_posts_with_location: number; points: { label: string; latitude: number; longitude: number; count: number; first_seen?: string | null; last_seen?: string | null; sources?: string[]; map_url?: string }[]; field_sources?: { field_key: string; source_type: string; updated_at: string }[] };
type Relationship = { id: string; related_profile_id: string; related_display_name: string; related_profile_type: "person" | "group"; relationship_type: string; direction: string; source_type: string; note?: string | null; confidence?: number | null; valid_from?: string | null; valid_to?: string | null };

import {ContactEventSidebar,ContactEvents} from "./contact-events";
import { ChatMonthly } from "./chat-monthly";
import { SourceAccountLinks } from "./source-account-links";
import { LoadMore } from "./load-more";
import { PhotoViewer } from "./photo-viewer";
import { MomentsCircle } from "./moments-circle";
import { SocialAnalytics } from "./social-analytics";
import { SocialFeed } from "./social-feed";
import { PlacesMap } from "./places-map";
import { ConversationView } from "./conversation-view";
import { RecordsView } from "./records-view";
import { RelationshipEditor } from "./relationship-editor";

export function ProfileView({ profileId }: { profileId: string }) {
  const searchParams = useSearchParams();
  const router=useRouter();
  const [photo,setPhoto]=useState<{src:string;alt:string}|null>(null);
  const [tab, setTab] = useState("overview");
  const [profile, setProfile] = useState<Profile | null>(null);
  const [sourceRevision,setSourceRevision]=useState(0);
  const [history, setHistory] = useState<Revision[]>([]);

  const [editing, setEditing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load(signal?: AbortSignal) {
    setLoading(true);
    try {
      const profileResponse = await fetch(`/api/v1/profiles/${profileId}`, {signal});
      if (!profileResponse.ok) throw new Error("profile not found");
      setProfile(await profileResponse.json());
      setError("");
    } catch {
      if (!signal?.aborted) setError("Could not load this person's profile. Try again.");
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }

  useEffect(() => { const abort=new AbortController();setProfile(null);setError("");void load(abort.signal);return()=>abort.abort(); }, [profileId]);
  useEffect(() => { setTab(searchParams.get("tab") || "overview"); }, [profileId, searchParams]);
  useEffect(() => {
    const abort=new AbortController();setHistory([]);
    if (tab === "history") fetch(`/api/v1/profiles/${profileId}/history`,{signal:abort.signal}).then(r => r.ok ? r.json() : []).then(setHistory).catch(()=>{});
    return()=>abort.abort();
  }, [tab, profileId]);

  if (loading && (!profile || profile.id!==profileId)) return <div className="page-wrap"><div className="data-loading">Loading profile…</div></div>;
  if (!profile || profile.id!==profileId) return <div className="page-wrap"><div className="empty-state"><Users size={22} /><strong>{error || "This person's profile was not found"}</strong><button className="button button-primary" onClick={()=>void load()}>Retry</button><Link className="button button-soft" href="/profiles">Back to people</Link></div></div>;

  const initials = profile.display_name.split(/\s+/).map((part) => part[0]).join("").slice(0, 2).toUpperCase();
  const identities = profile.identities ?? [];
  const avatarUrl = profile.avatar_media_id ? `/api/v1/media/${profile.avatar_media_id}` : profile.avatar_url || undefined;
  const coverUrl = profile.cover_media_id ? `/api/v1/media/${profile.cover_media_id}` : profile.cover_url || undefined;
  const sourceCount = new Set(identities.filter(i=>i.provider!=="monica").map((item) => item.provider)).size;
  const identityLinks = compactIdentities(identities.filter(i => i.provider !== "monica"));
  return <div className="page-wrap profile-page">
    <div className="breadcrumb"><Link href="/dashboard"><ArrowLeft size={15} />Overview</Link><span>/</span><Link href="/profiles">People</Link><span>/</span><span>{profile.display_name}</span></div>
    <div className="profile-hero">
      {coverUrl && <button className="profile-cover" onClick={()=>setPhoto({src:coverUrl,alt:`${profile.display_name}'s Moments cover`})} aria-label="View full-size cover"><img src={coverUrl} width={1200} height={400} alt="WeChat Moments cover"/><span>View original</span></button>}
      <div className="profile-avatar">{avatarUrl ? <button className="avatar-button" onClick={()=>setPhoto({src:avatarUrl,alt:`${profile.display_name}'s avatar`})} aria-label="View full-size avatar"><img width={96} height={96} className="profile-avatar-image" src={avatarUrl} alt={`${profile.display_name} avatar`} /></button> : initials || "M"}</div>
      <div className="profile-title">
        <div className="profile-name-row"><h1>{profile.display_name}</h1><span className="verified-pill">{profile.profile_type === "group" ? "WeChat group" : sourceCount ? `${sourceCount} sources recorded` : "Sources still needed"}</span></div>
        <p className="muted profile-intro">{profile.summary || (profile.profile_type === "group" ? "WeChat group" : "")}</p>
        <div className="profile-links">{profile.profile_type==="person"&&<span><MapPin size={14} />{profileAddress(profile) || "No address"}</span>}{identityLinks.filter((identity) => identity.profile_url?.startsWith("http")).slice(0, 4).map((identity) => <a href={identity.profile_url || "#"} target="_blank" rel="noreferrer" key={identity.id}><>{identity.provider === "linkedin" && profile.linkedin_avatar_media_id ? <img className="provider-avatar" src={`/api/v1/media/${profile.linkedin_avatar_media_id}`} alt="LinkedIn avatar" /> : <ProviderIcon provider={identity.provider} />}</>{providerLabel(identity.provider)} <ExternalLink size={11} /></a>)}</div>
        <div className="identity-strip">{identityLinks.slice(0, 8).map((identity) => <span className="identity-chip" title={identity.external_id} key={identity.id}><strong>{providerLabel(identity.provider)}</strong><span>{compactIdentityLabel(identity)}</span></span>)}{identityLinks.length > 8 && <span className="identity-more">+{identityLinks.length - 8} more sources</span>}</div>
      </div>
      {!!profile.platform_avatars?.length&&<div className="source-avatars">{profile.platform_avatars.map(avatar=><button key={`${avatar.provider}:${avatar.media_id}`} onClick={()=>setPhoto({src:`/api/v1/media/${avatar.media_id}`,alt:`${profile.display_name}'s ${providerLabel(avatar.provider)} avatar`})}><img src={`/api/v1/media/${avatar.media_id}?variant=thumb`} alt={`${providerLabel(avatar.provider)} avatar`} width={32} height={32} loading="lazy"/><span>{providerLabel(avatar.provider)}</span></button>)}</div>}
      <div className="profile-actions"><SourceAccountLinks profileId={profileId} profileType={profile.profile_type} onChanged={()=>{setSourceRevision(n=>n+1);void load();}}/><button className="button button-primary profile-edit-button" onClick={() => setEditing((value) => !value)}><Edit3 size={15} />{editing ? "Close editor" : "Edit profile"}</button></div>
    </div>
    {editing && <FieldEditor profileId={profileId} profile={profile} onSaved={() => { setEditing(false); void load(); }} />}
    <div className="profile-layout" key={`${profileId}:${sourceRevision}`}>
      <ProfileSidebar key={profileId} profile={profile} profileId={profileId} onEdit={()=>setEditing(true)}/>
      <main className="profile-main">
        <div className="profile-tabs">{[["overview", profile.profile_type==="group"?"Group profile":"Profile and stats"], ...(profile.profile_type==="person"?[["timeline", "Updates and photos"]]:[]), ["records", "Notes and records"], ["contact-events","Calls and money"], ["relationships", profile.profile_type==="group"?"Members":"Relationships"], ["messages", "Chat"], ["history", "History"]].map(([id, label]) => <button className={tab === id ? "selected" : ""} onClick={() => {setTab(id);router.replace(`/profiles/${profileId}?tab=${id}`,{scroll:false});}} aria-pressed={tab===id} key={id}>{label}</button>)}</div>
        {tab === "overview" && (profile.profile_type==="group"?<GroupOverview profile={profile}/>:<><PlatformBios profile={profile}/><Overview profileId={profileId} profile={profile}/></>)}
        {tab === "timeline" && (profile.profile_type==="group"?<RecordsView profileId={profileId}/>:<SocialFeed profileId={profileId} />)}
        {tab === "relationships" && (profile.profile_type==="group"?<GroupOverview profile={profile}/>:<Relationships profileId={profileId} />)}
        {tab === "messages" && <ConversationView profileId={profileId}/>}
        {tab === "records" && <RecordsView profileId={profileId}/>}
        {tab === "contact-events" && <ContactEvents profileId={profileId} kind={searchParams.get("kind")||"call"}/>}
        {tab === "history" && <HistoryView history={history} />}
      </main>
    </div>
    {photo&&<PhotoViewer {...photo} onClose={()=>setPhoto(null)}/>}
  </div>;
}

function ProfileSidebar({ profile, profileId, onEdit }: { profile: Profile; profileId: string; onEdit:()=>void }) {
  const [relationships, setRelationships] = useState<Relationship[]>([]);
  useEffect(() => { if(profile.profile_type!=="person")return;const abort=new AbortController();fetch(`/api/v1/profiles/${profileId}/relationships`,{signal:abort.signal}).then((response) => response.ok ? response.json() : []).then(setRelationships).catch(() => {});return()=>abort.abort(); }, [profileId,profile.profile_type]);
  const grouped = useMemo(() => distinctRelationships(relationships.filter(item => !item.id.startsWith("membership:"))).reduce<Record<string, Relationship[]>>((acc, item) => { (acc[item.relationship_type] ||= []).push(item); return acc; }, {}), [relationships]);
  const [members, setMembers] = useState<GroupLink[]>(profile.group_members ?? []);
  const [membersLoading,setMembersLoading]=useState(false);
  const [allGroups,setAllGroups]=useState(false);
  async function moreMembers(){setMembersLoading(true);try{const response=await fetch(`/api/v1/groups/${profileId}/members?offset=${members.length}`);if(response.ok){const rows=await response.json();setMembers(previous=>[...previous,...rows]);}}finally{setMembersLoading(false);}}
  const owners = profile.group_owners ?? [];
  const groups = profile.member_of_groups ?? [];
  return <aside className="profile-sidebar-panel">
    <ManualDetails profile={profile} onEdit={onEdit}/><WeChatDetails profile={profile}/><ContactEventSidebar profileId={profileId}/>
    {!!profile.tags?.length&&<section className="sidebar-section profile-tags"><h2><Tags size={15}/>Tags</h2><div>{profile.tags.map(tag=><Link href={`/profiles?tag=${tag.id}`} key={tag.id} title={providerLabel(tag.source_type)}>{tag.name}</Link>)}</div></section>}
    {profile.profile_type==="person"&&<section className="sidebar-section"><div className="sidebar-section-header"><span><Link2 size={15} />Relationship graph</span><Link href={`/relationships?focus=${profileId}`} aria-label="Open the relationship graph"><ChevronRight size={15} /></Link></div>{Object.keys(grouped).length ? <div className="sidebar-links">{Object.entries(grouped).slice(0, 8).map(([type, entries]) => <div className="relationship-section" key={type}><small>{relationshipLabel(type)} · {entries.length}</small>{entries.slice(0, 5).map((item) => <Link className="sidebar-link" href={`/profiles/${item.related_profile_id}`} key={item.id}><span className="sidebar-avatar">{item.related_display_name.slice(0, 1)}</span><span>{item.related_display_name}</span><ChevronRight size={13} /></Link>)}{entries.length > 5 && <small className="sidebar-more">{entries.length - 5} more relationships</small>}</div>)}</div> : <p className="sidebar-empty">No confirmed relationships yet</p>}</section>}
    {profile.profile_type === "group" ? <><section className="sidebar-section"><div className="sidebar-section-header"><span><UsersRound size={15} />Group members</span><b>{profile.group_member_count ?? members.length}</b></div><div className="sidebar-links">{members.map((member) => <Link className="sidebar-link" href={`/profiles/${member.person_profile_id}`} key={member.person_profile_id}><span className="sidebar-avatar">{member.display_name.slice(0, 1)}</span><span>{member.display_name}</span><small>{member.role==="owner"?"Owner":member.role==="admin"?"Admin":"Member"}</small><ChevronRight size={13} /></Link>)}{members.length < (profile.group_member_count || 0) && <button className="button button-soft" disabled={membersLoading} onClick={()=>void moreMembers()}>{membersLoading ? "Loading…" : `Load more members (${members.length}/${profile.group_member_count})`}</button>}</div></section><section className="sidebar-section"><div className="sidebar-section-header"><span><ShieldCheck size={15} />Group owners</span><b>{owners.length}</b></div><div className="sidebar-links">{owners.slice(0, 8).map((owner) => <Link className="sidebar-link" href={`/profiles/${owner.person_profile_id}`} key={owner.person_profile_id}><span className="sidebar-avatar">{owner.display_name.slice(0, 1)}</span><span>{owner.display_name}</span><small>Owner</small><ChevronRight size={13} /></Link>)}{!owners.length && <p className="sidebar-empty">This import has no clear group owner</p>}</div></section></> : <section className="sidebar-section"><div className="sidebar-section-header"><span><UsersRound size={15} />WeChat groups</span><b>{profile.linked_group_count ?? groups.length}</b></div><div className="sidebar-links">{groups.slice(0, allGroups?groups.length:12).map((group) => <Link className="sidebar-link" href={`/profiles/${group.group_profile_id}`} key={group.group_profile_id}><span className="sidebar-avatar group">{group.display_name.slice(0, 1)}</span><span>{group.display_name}</span><small>{group.role==="owner"?"Owner":group.role==="admin"?"Admin":"Member"}</small><ChevronRight size={13} /></Link>)}{groups.length>12&&<button className="button button-soft" onClick={()=>setAllGroups(v=>!v)}>{allGroups?"Hide group list":`View all ${groups.length} groups`}</button>}{!groups.length && <p className="sidebar-empty">Not linked to any WeChat groups</p>}</div></section>}

  </aside>;
}

function GroupOverview({profile}:{profile:Profile}){
 const [members,setMembers]=useState(profile.group_members||[]),[busy,setBusy]=useState(false),[error,setError]=useState("");
 async function more(){if(busy)return;setBusy(true);setError("");try{const r=await fetch(`/api/v1/groups/${profile.id}/members?offset=${members.length}`);if(!r.ok)throw new Error();const next:GroupLink[]=await r.json();setMembers(old=>[...old,...next.filter(n=>!old.some(m=>m.person_profile_id===n.person_profile_id))]);}catch{setError("Could not load members. Try again.");}finally{setBusy(false);}}
 const reported=profile.presentation?.sources.wechat?.member_count;
 const stats=profile.group_summary;
 return <section className="panel profile-card group-dossier"><div className="panel-heading"><div><h2><UsersRound size={18}/>Group members</h2><p className="muted">{profile.group_member_count} linked members{reported!=null?` · WeChat recorded ${reported}`:""}</p></div><Link className="button button-soft" href={`/profiles/${profile.id}?tab=messages`}>Open group chat</Link></div>
 {stats&&<div className="group-chat-summary"><span><b>{stats.messages.toLocaleString("en-US")}</b> group messages</span><span><b>{stats.active_senders}</b> senders</span>{stats.last&&<span>Last message {formatDate(stats.last)}</span>}<small>Chatlog archive summary</small></div>}
 <div className="group-member-grid">{members.map(member=><Link href={`/profiles/${member.person_profile_id}`} key={member.person_profile_id}><span className="sidebar-avatar">{member.avatar_media_id?<img loading="lazy" width={36} height={36} alt="" src={`/api/v1/media/${member.avatar_media_id}?variant=thumb`}/>:member.display_name.slice(0,1)}</span><span><strong>{member.display_name}</strong><small>{member.role==="owner"?"Owner":member.role==="admin"?"Admin":"Member"}</small></span><ChevronRight size={14}/></Link>)}</div>
 {error&&<p role="alert">{error}</p>}{members.length<(profile.group_member_count||0)&&<LoadMore cursor={String(members.length)} busy={busy} error={!!error} onLoad={()=>void more()} label="Load more members"/>}
 </section>;
}

function FieldEditor({ profileId, profile, onSaved }: { profileId: string; profile: Profile; onSaved: () => void }) {
  const [fieldKey, setFieldKey] = useState("summary");
  const [customKey,setCustomKey]=useState("");
  const [value, setValue] = useState(profile.summary || "");
  const choices:Record<string,string>={display_name:"Name or group name",summary:"Summary",biography:"Personal notes",address:"Address",custom:"Other details"};
  function choose(key:string){setFieldKey(key);setValue(key==="display_name"?profile.display_name:key==="summary"?profile.summary||"":String(profile.fields?.find(f=>f.field_key===key)?.value||""));}
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function save() { setBusy(true); setError(""); const parsed = value; const response = await apiFetch(`/api/v1/profiles/${profileId}/fields`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ field_key: fieldKey==="custom"?customKey:fieldKey, value: parsed }) }); if (response.ok) onSaved(); else setError("Save failed. Try again later."); setBusy(false); }
  return <section className="edit-panel"><div className="edit-panel-row"><label>Profile field<select value={fieldKey} onChange={event=>choose(event.target.value)}>{Object.entries(choices).map(([key,label])=><option value={key} key={key}>{label}</option>)}</select></label>{fieldKey==="custom"&&<input value={customKey} onChange={event=>setCustomKey(event.target.value)} aria-label="Field name" placeholder="For example, food preferences or interests"/>}<span className="muted">Changes appear in history after you save</span></div><textarea value={value} onChange={(event) => setValue(event.target.value)} placeholder="Enter a value…" aria-label="Field value" /><div className="edit-panel-actions"><button className="button button-soft" onClick={onSaved}>Cancel</button><button className="button button-primary" onClick={save} disabled={busy || (fieldKey==="custom"&&!customKey.trim()) || (fieldKey==="display_name"&&!value.trim())}><Save size={14} />{busy ? "Saving…" : "Save new version"}</button></div>{error && <p className="form-error">{error}</p>}</section>;
}

function fieldSource(field: Field): string {
  if (/^wechat[.]|^Monica · 微信|^Monica · 朋友圈|^Monica · 群/.test(field.field_key)) return "wechat";
  if (/^linkedin[.]|LinkedIn/i.test(field.field_key)) return "linkedin";
  if (/^instagram[.]|Instagram/i.test(field.field_key) || field.current_source_type === "instagram") return "instagram";
  return "manual";
}
function visibleField(field: Field): boolean {
  const key = field.field_key;
  if (/snapshot|hash|partial|coverage|archived_at|synced_at|match_note|profile_pic|avatar|cover_url|internal_id|group_id|group_stats|direct_stats|moments_summary|location_history|custom_fields|好友来源|统计截至|内部.?ID|群.?ID|群主微信 ID|已关联成员|联系人类型|群活动|群发言统计|群内显示名|私聊统计|共同群|消息数|消息总数|直接消息|群内消息|首次直接|最近直接|首次群内|最近群内|朋友圈关系分|朋友圈最常互动|朋友圈足迹|raw/i.test(key)) return false;
  if (typeof field.value === "object" && !Array.isArray(field.value)) return false;
  return field.value != null && field.value !== "" && (!Array.isArray(field.value) || field.value.length > 0);
}
function textValue(value:unknown):string {return Array.isArray(value)?value.map(textValue).join("\n"):typeof value==="string"?value.replace(/\\n/g,"\n"):typeof value==="number"?String(value):typeof value==="boolean"?(value?"Yes":"No"):"";}
function PlatformBios({profile}:{profile:Profile}){
 const sources=profile.presentation?.sources||{};
 return <div className="platform-bios">{["wechat","instagram","linkedin"].map(source=>{
 const data=sources[source]||{};const bio=source==="instagram"&&(profile.presentation?.instagram_accounts?.length||0)>1?profile.presentation!.instagram_accounts!.filter(a=>a.biography).map(a=>`@${a.username}\n${textValue(a.biography)}`).join("\n\n"):textValue(data.biography||data.about||data.signature);const headline=textValue(data.headline);
 if(!bio&&!headline)return null;
 return <section key={source} className={`platform-bio ${source}`}><h2><ProviderIcon provider={source}/>{providerLabel(source)} bio</h2>{headline&&<strong>{headline}</strong>}{bio&&<details><summary><span>{bio}</span></summary><p>{bio}</p></details>}</section>;
 })}</div>;
}
function WeChatDetails({profile}:{profile:Profile}){
 const data=profile.presentation?.sources.wechat||{};
 const region=textValue(data.region)||[data.country,data.province,data.city].filter(Boolean).join(" · ");
 const rows=profile.profile_type==="group"?[["Group name",data.nickname],["Remark",data.remark]]:[["WeChat ID",data.alias],["Nickname",data.nickname],["Remark",data.remark],["Region",region],["How added",data.add_source],["First seen in a group",data.first_group_seen],["Last seen in a group",data.last_group_seen]];
 if(!rows.some(([,value])=>value)&&!data.group_nicknames)return null;
 return <section className="sidebar-section wechat-dossier"><h2><MessageCircle size={17}/>WeChat profile</h2><dl>{rows.filter(([,value])=>value).map(([label,value])=><div key={String(label)}><dt>{String(label)}</dt><dd>{textValue(value)}</dd></div>)}</dl>{data.group_nicknames?<details className="group-nicknames"><summary>Display names in WeChat groups</summary><p>{textValue(data.group_nicknames)}</p></details>:null}{data.signature?<p className="sidebar-signature">{textValue(data.signature)}</p>:null}</section>;
}
function ManualDetails({profile,onEdit}:{profile:Profile;onEdit:()=>void}){
 const manual=expandedFields(profile.fields||[]).filter(f=>fieldSource(f)==="manual"&&visibleField(f)&&!["display_name","summary","monica.name","monica.birthdate_approximate"].includes(f.field_key));
 return <section className="sidebar-section manual-dossier"><div className="sidebar-section-header"><h2>Manual details</h2><button className="icon-button" onClick={onEdit} aria-label="Edit manual details"><Edit3 size={16}/></button></div>{manual.length?<dl>{manual.map(f=><div key={f.field_key}><dt>{fieldLabel(f.field_key)}</dt><dd><ReadableValue value={f.value}/></dd></div>)}</dl>:<button className="sidebar-add" onClick={onEdit}>Add notes or details</button>}</section>;
}
function Overview({ profileId, profile }: { profileId: string; profile: Profile }) {
 const facts=profile.presentation?.facts||profile.structured_facts||[];
 const linkedin=profile.presentation?.sources.linkedin||{},instagram=profile.presentation?.sources.instagram||{};
 return <div className="profile-columns">
 <ChatMonthly profileId={profileId}/>
 {!!Object.keys(linkedin).length&&<section className="panel profile-card professional-dossier"><div className="panel-heading"><h2><Linkedin size={18}/> LinkedIn · Experience</h2>{textValue(linkedin.profile_url)&&<a className="panel-link" target="_blank" rel="noreferrer" href={textValue(linkedin.profile_url)}>Open profile <ExternalLink size={14}/></a>}</div>
 <div className="dossier-meta">{textValue(linkedin.location)&&<span><MapPin size={14}/>{textValue(linkedin.location)}</span>}{textValue(linkedin.connected_on)&&<span>Connected {textValue(linkedin.connected_on)}</span>}{linkedin.open_to_work===true&&<span>Open to work</span>}</div>
 <div className="career-columns">{["employment","education"].map(type=><section key={type}><h3>{type==="employment"?<BriefcaseBusiness size={16}/>:<GraduationCap size={16}/>} {type==="employment"?"Work":"Education"}</h3><div className="career-timeline">{facts.filter(f=>f.fact_type===type).map((f,i)=><FactCard fact={f} key={i}/>)}{!facts.some(f=>f.fact_type===type)&&<p className="muted">Nothing archived yet</p>}</div></section>)}</div></section>}
 {!!Object.keys(instagram).length&&<section className="panel profile-card instagram-dossier"><div className="panel-heading"><h2><Instagram size={18}/> Instagram · Photos</h2>{textValue(instagram.profile_url)&&<a className="panel-link" href={textValue(instagram.profile_url)} target="_blank" rel="noreferrer">Open profile <ExternalLink size={14}/></a>}</div><div className="dossier-numbers">{[["Followers",instagram.followers_count],["Following",instagram.followees_count],["Profile posts",instagram.media_count]].filter(([,v])=>v!=null).map(([label,value])=><div key={String(label)}><strong>{Number(value).toLocaleString("en-US")}</strong><span>{String(label)}</span></div>)}</div><p className="muted">Profile counts are as of collection time. Archived posts are in the stats below.</p></section>}
 <SocialAnalytics profileId={profileId}/>
 <LocationSummary profileId={profileId}/>

 </div>;
}

function LocationSummary({ profileId }: { profileId: string }) {
  const [summary, setSummary] = useState<LocationSummary | null>(null);
  useEffect(() => { fetch(`/api/v1/profiles/${profileId}/locations`).then((response) => response.ok ? response.json() : null).then(setSummary).catch(() => setSummary(null)); }, [profileId]);
  return <section className="panel profile-card location-card"><div className="panel-heading"><div><h2><MapPinned size={17} /> Places</h2><p className="muted">Shown from post coordinates and archived traces.</p></div><MapPin size={17} className="panel-icon" /></div>{!summary ? <div className="data-loading">Loading place statistics…</div> : summary.points.length ? <><PlacesMap points={summary.points}/><div className="location-stats"><strong>{summary.place_count}</strong><span>places</span><strong>{summary.total_posts_with_location}</strong><span>located events</span></div><div className="location-list">{summary.points.slice(0, 8).map((point) => <div className="location-row" key={`${point.label}-${point.latitude}-${point.longitude}`}><span className="location-pin"><MapPin size={14} /></span><span><strong>{point.label}</strong><small>{point.count} times · {point.sources?.map(providerLabel).join(" · ") || "Imported"} · {formatDate(point.last_seen)}</small></span>{point.map_url && <a href={point.map_url} target="_blank" rel="noreferrer" aria-label={`Open ${point.label} on the map`}><ExternalLink size={14} /></a>}</div>)}</div>{summary.points.length > 8 && <p className="muted location-more">The map includes all {summary.points.length} places.</p>}</> : <div className="empty-state"><MapPin size={20} /><strong>No locatable places yet</strong><span>After you import Moments posts with coordinates, LinkedIn addresses, or a manual address, they are grouped here.</span></div>}</section>;
}
function Detail({ label, value, source }: { label: string; value: unknown; source: string }) { return <div className="detail-row"><dt>{label}</dt><dd><ReadableValue value={value} /><small>{source}</small></dd></div>; }
function Stat({ label, value, detail }: { label: string; value: string; detail: string }) { return <div className="stat-item"><span>{label}</span><strong>{value}</strong><small>{detail}</small></div>; }

function Timeline({ profileId, items }: { profileId: string; items: TimelineItem[] }) {
  const [provider, setProvider] = useState("all");
  const [selected, setSelected] = useState<TimelineItem | null>(null);
  const [detail, setDetail] = useState<TimelineDetail | null>(null);
  const [summary, setSummary] = useState<TimelineSummary | null>(null);
  useEffect(() => { fetch(`/api/v1/timeline/summary?profile_id=${encodeURIComponent(profileId)}`).then((response) => response.ok ? response.json() : null).then(setSummary).catch(() => setSummary(null)); }, [profileId]);
  const providers = ["wechat", "instagram", "linkedin", "manual"];
  const sections = provider === "all" ? providers : [provider];
  async function open(item: TimelineItem) { setSelected(item); setDetail(null); const response = await fetch(`/api/v1/timeline/${item.id}?provider=${encodeURIComponent(item.provider)}`); if (response.ok) setDetail(await response.json()); }
  return <section className="panel timeline-detail"><div className="panel-heading"><div><h2>Timeline by source</h2><p className="muted">WeChat Moments, Instagram, LinkedIn, and manual activities are shown separately. Click an event to load the full text, versions, interactions, and media.</p></div><div className="filter-pills">{[["all", "All"], ["wechat", "WeChat"], ["instagram", "Instagram"], ["linkedin", "LinkedIn"], ["manual", "Activity"]].map(([id, label]) => <button className={provider === id ? "selected" : ""} onClick={() => setProvider(id)} key={id}>{label}</button>)}</div></div><div className="timeline-source-grid">{providers.map((source) => { const stats = summary?.providers[source]; return <button type="button" className={`timeline-source-card ${provider === source ? "selected" : ""}`} onClick={() => setProvider(source)} key={source}><span className={`source-icon ${providerColor(source)}`}><ProviderIcon provider={source} /></span><span><strong>{providerLabel(source)}</strong><small>{stats ? `${stats.events} events · ${stats.media} media` : "Loading stats…"}</small></span><b>{stats ? stats.likes + stats.comments : "—"}</b></button>; })}</div>{sections.map((source) => { const sourceItems = items.filter((item) => item.provider === source); const stats = summary?.providers[source]; return <section className={`timeline-source-section ${provider === "all" ? "timeline-source-section-separated" : ""}`} key={source}><div className="timeline-source-heading"><div><h3><ProviderIcon provider={source} /> {providerLabel(source)}</h3><p>{stats ? `${stats.events} events · ${stats.media} media · ${stats.likes} likes · ${stats.comments} comments` : "Loading source stats"}</p></div><span>{stats?.latest ? `Latest ${formatDate(stats.latest)}` : ""}</span></div>{sourceItems.length ? <div className="timeline-detail-list">{sourceItems.map((item) => <TimelineEvent key={`${item.provider}-${item.external_id}`} item={item} source={item.provider} title={item.title} date={formatDate(item.occurred_at)} summary={item.summary} color={providerColor(item.provider)} onOpen={() => void open(item)} />)}</div> : <div className="timeline-source-empty">This source has no events to show yet.</div>}</section>; })}{selected && <TimelineDetailCard item={selected} detail={detail} onClose={() => { setSelected(null); setDetail(null); }} />}</section>;
}
function TimelineEvent({ item, source, title, date, summary, color, onOpen }: { item: TimelineItem; source: string; title: string; date: string; summary?: string | null; color: string; onOpen: () => void }) { return <button type="button" className="timeline-event timeline-event-button" onClick={onOpen}><span className={`timeline-marker ${color}`} /><span className="timeline-event-copy"><span className="item-source">{providerLabel(source)} · {date}</span><strong>{title}</strong>{summary && <small className="timeline-summary-text">{summary}</small>}<span className="timeline-event-stats">{(item.media_count ?? 0) > 0 && <span><Images size={12} /> {item.media_count}</span>}{(item.like_count ?? 0) > 0 && <span><Heart size={12} /> {item.like_count}</span>}{(item.comment_count ?? 0) > 0 && <span><MessageSquare size={12} /> {item.comment_count}</span>}{item.location && <span><MapPin size={12} /> Has location</span>}</span>{item.media?.length ? <span className="timeline-inline-media">{item.media.slice(0, 3).map((media, index) => <MediaPreview media={media} alt={`${providerLabel(source)} media ${index + 1}`} key={`${media.source_url || media.thumbnail_url || index}`} />)}</span> : null}</span><span className="timeline-event-arrow" aria-hidden="true"><ChevronRight size={15} /></span></button>; }
function MediaPreview({ media, alt }: { media: TimelineMedia; alt: string }) { const src = media.id ? `/api/v1/media/${media.id}` : (media.thumbnail_url || media.source_url || ""); return src ? <img src={src} alt={alt} loading="lazy" /> : <span className="media-placeholder">Media</span>; }
function TimelineDetailCard({ item, detail, onClose }: { item: TimelineItem; detail: TimelineDetail | null; onClose: () => void }) { const content = detail?.content && typeof detail.content === "object" ? detail.content as Record<string, unknown> : {}; const contentMedia = Array.isArray(content.media) ? content.media as TimelineMedia[] : []; const media = detail?.media?.length ? detail.media : contentMedia; const interactions = detail?.interactions ?? []; return <div className="timeline-detail-card"><div className="panel-heading"><div><h3>{detail?.title || item.title}</h3><p className="muted">{providerLabel(item.provider)} · {formatDate(item.occurred_at)}{detail?.profile_display_name ? ` · ${detail.profile_display_name}` : ""}</p></div><button className="icon-button" onClick={onClose} aria-label="Close event details">×</button></div>{detail ? <><p className="muted">{detail.coverage_status ? `Coverage: ${detail.coverage_status}` : "Full event details loaded"}</p>{(content.like_count || content.comment_count || interactions.length) ? <div className="interaction-summary"><span><Heart size={14} /> {String(content.like_count ?? interactions.filter((interaction) => interaction.interaction_type === "like").length)} likes</span><span><MessageSquare size={14} /> {String(content.comment_count ?? interactions.filter((interaction) => ["comment", "reply"].includes(interaction.interaction_type)).length)} comments</span></div> : null}{media.length ? <div className="timeline-media-grid">{media.map((entry, index) => entry.media_type === "video" && (entry.id || entry.source_url) ? <video controls preload="metadata" src={entry.id ? `/api/v1/media/${entry.id}` : entry.source_url || undefined} key={`${entry.id || entry.source_url}-${index}`} /> : <MediaPreview media={entry} alt={`Timeline media ${index + 1}`} key={`${entry.id || entry.source_url || index}`} />)}</div> : null}{interactions.length ? <div className="interaction-list"><strong>Interactions</strong>{interactions.slice(0, 24).map((interaction) => <div key={interaction.id}><span>{interaction.interaction_type === "like" ? "Like" : interaction.interaction_type === "reply" ? "Reply" : "Comment"}</span><b>{interaction.author_name || interaction.author_external_id || "Unknown user"}</b><small>{interaction.content && typeof interaction.content === "object" && "text" in interaction.content ? String((interaction.content as Record<string, unknown>).text || "") : String(interaction.metadata?.text || "")}</small></div>)}</div> : null}<div className="event-body">{String(content.text || content.caption || content.body || detail.summary || "")}</div></> : <div className="data-loading">Loading event text…</div>}</div>; }

function Relationships({ profileId }: { profileId: string }) {
  const [relationships, setRelationships] = useState<Relationship[]>([]);
  const [revision,setRevision]=useState(0);
  useEffect(() => { fetch(`/api/v1/profiles/${profileId}/relationships`).then((response) => response.ok ? response.json() : []).then(setRelationships).catch(() => setRelationships([])); }, [profileId,revision]);
  const grouped = useMemo(() => distinctRelationships(relationships).reduce<Record<string, Relationship[]>>((acc, item) => { (acc[item.relationship_type] ||= []).push(item); return acc; }, {}), [relationships]);
  return <div className="profile-columns"><MomentsCircle profileId={profileId}/><section className="panel profile-card"><div className="panel-heading"><div><h2>Relationship types</h2><p className="muted">Confirmed people, group members, and owners. Click to open a profile.</p></div><Link className="button button-soft" href={`/relationships?focus=${profileId}`}>View graph</Link></div><RelationshipEditor profileId={profileId} onSaved={()=>setRevision(v=>v+1)}/>{relationships.length ? <div className="relationships-list">{Object.entries(grouped).map(([type, entries]) => <section className="relationship-section" key={type}><h3>{relationshipLabel(type)}<small>{entries.length}</small></h3>{entries.map((relationship) => <Link className="relationship-row" href={`/profiles/${relationship.related_profile_id}`} key={relationship.id}><span className="sidebar-avatar">{relationship.related_display_name.slice(0, 1)}</span><span><strong>{relationship.related_display_name}</strong><small>{relationship.direction === "both"?"Both directions":relationship.direction === "incoming" ? "Them → you" : "You → them"} · {relationship.source_type}</small></span><ChevronRight size={15} /></Link>)}</section>)}</div> : <div className="empty-state"><Users size={20} /><strong>No relationships yet</strong><span>Imported or manually added relationships will show up here.</span></div>}</section></div>;
}

function HistoryView({ history }: { history: Revision[] }) {
  const meaningful=useMemo(()=>history.flatMap(entry=>entry.field_key==='monica.custom_fields' && entry.value && typeof entry.value==='object' ? Object.entries(entry.value as Record<string,unknown>).map(([key,value])=>({...entry,id:`${entry.id}:${key}`,field_key:`Monica · ${key}`,value})) : [entry]).filter(entry=>visibleField({...entry,current_source_type:entry.source_type,updated_at:entry.observed_at})),[history]);
  const rows = meaningful.slice(0,120).map((entry,index)=>({entry,previous:meaningful.slice(index+1).find(candidate=>candidate.field_key===entry.field_key&&candidate.source_type===entry.source_type)}));
  return <section className="panel history-panel"><div className="panel-heading"><div><h2>Field history</h2><p className="muted">Real changes to this profile, compared before and after by source.</p></div><span className="history-count">{meaningful.length} profile versions</span></div>{rows.length?<div className="history-list">{rows.map(({entry,previous})=><HistoryRow key={entry.id} field={entry.field_key} from={previous?valueText(previous.value):"First recorded"} to={valueText(entry.value)} source={`${entry.source_type}${entry.is_conflict?" · conflict candidate":""}`} date={formatDate(entry.observed_at)}/>)}</div>:<p className="muted">No profile changes yet.</p>}</section>;
}
function HistoryRow({ field, from, to, source, date }: { field: string; from: string; to: string; source: string; date: string }) { return <div className="history-row"><div className="history-field"><strong>{fieldLabel(field)}</strong><small>{source} · {date}</small></div><div className="diff"><span className="diff-from">{from}</span><span className="diff-arrow">→</span><span className="diff-to">{to}</span></div></div>; }

function ReadableValue({ value }: { value: unknown; rawLabel?: string }) {
  if (typeof value === "string") return /^https?:\/\//.test(value) ? <a href={value} target="_blank" rel="noreferrer">{value}<ExternalLink size={12}/></a> : <span className="value-summary">{value}</span>;
  if (Array.isArray(value)) return <span className="value-block">{value.map((item,index) => <ReadableValue value={item} key={index}/>)}</span>;
  return <span className="value-summary">{summarizeValue(value)}</span>;
}
function summarizeValue(value: unknown): string { if (value === null || value === undefined || value === "") return "—"; if (typeof value === "string") return value.length > 220 ? `${value.slice(0, 220)}…` : value; if (typeof value === "number" || typeof value === "boolean") return typeof value === "boolean" ? (value ? "Yes" : "No") : String(value); if (Array.isArray(value)) return value.length ? `${value.length} items · ${value.slice(0, 3).map(summarizeValue).join(", ")}${value.length > 3 ? "…" : ""}` : "Empty list"; if (typeof value === "object") { const item = value as Record<string, unknown>; if ("n" in item || "count" in item) return `Total ${valueText(item.n ?? item.count)}${item.sent !== undefined ? ` · sent ${valueText(item.sent)}` : ""}${item.recv !== undefined ? ` · received ${valueText(item.recv)}` : ""}`; if ("places" in item && Array.isArray(item.places)) return `${item.places.length} places`; const keys = Object.keys(item); return keys.length ? keys.slice(0, 4).map((key) => `${key}: ${summarizeValue(item[key]).slice(0, 54)}`).join(" · ") : "Empty object"; } return String(value); }
function valueText(value: unknown): string { return summarizeValue(value); }
function formatDate(value?: string | null): string { if (!value) return "No date recorded"; const date = new Date(value); return Number.isNaN(date.getTime()) ? String(value) : new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeStyle: "short" }).format(date); }
function providerColor(provider: string): string { const normalized = provider.toLowerCase(); return normalized === "instagram" ? "violet" : normalized === "linkedin" ? "amber" : normalized === "manual" ? "rose" : "teal"; }
function providerLabel(provider: string): string { return provider === "wechat" ? "WeChat" : provider === "wechat_group" ? "WeChat group" : provider === "linkedin" ? "LinkedIn" : provider === "instagram" ? "Instagram" : provider === "monica" ? "Monica" : provider; }
function ProviderIcon({ provider }: { provider: string }) { return provider === "linkedin" ? <Linkedin size={14} /> : provider === "instagram" ? <Instagram size={14} /> : <Link2 size={14} />; }
function compactIdentityLabel(identity: Identity & { sourceCount?: number }): string { const value = identity.username || identity.display_name || identity.external_id; return value.length > 32 ? `${value.slice(0, 29)}…` : value; }
function compactIdentities(identities: Identity[]): (Identity & { sourceCount: number })[] { const map = new Map<string, Identity & { sourceCount: number }>(); for (const identity of identities) { const key = `${identity.provider}:${identity.username || identity.profile_url || identity.external_id}`.toLowerCase(); const current = map.get(key); if (current) current.sourceCount += 1; else map.set(key, { ...identity, sourceCount: 1 }); } return [...map.values()]; }
function profileAddress(profile: Profile): string { const field = profile.fields?.find((item) => item.field_key.includes("address") || item.field_key.includes("location") || item.field_key === "wechat.city"); return field ? summarizeValue(field.value) : ""; }
function fieldLabel(fieldKey: string): string { if(/^instagram.accounts.[^.]+./.test(fieldKey)) return fieldLabel(fieldKey.replace(/^instagram.accounts.[^.]+./,"instagram.")); const labels: Record<string, string> = { "display_name":"Name or group name", "summary":"Summary", "biography":"Personal notes", "monica.nickname":"Contact remark", "monica.food_preferences":"Food preferences", "monica.first_met_where":"Where you first met", "monica.first_met_additional_info":"How you met", "monica.job":"Job title", "monica.company":"Company", "address":"Address", "wechat.alias": "WeChat ID", "wechat.remark": "WeChat remark", "wechat.nickname": "WeChat nickname", "wechat.signature": "WeChat signature", "wechat.add_source": "How you added them on WeChat", "wechat.historical_nicknames": "WeChat nickname history", "wechat.country": "WeChat country", "wechat.province": "WeChat province", "wechat.city": "WeChat city", "wechat.group_id": "WeChat group ID", "wechat.owner": "WeChat group owner ID", "wechat.member_count": "Group member count", "wechat.group_stats": "WeChat group chat stats", "wechat.direct_stats": "WeChat private chat stats", "wechat.moments_summary": "Moments relationship stats", "wechat.location_history": "Moments places", "linkedin.about": "LinkedIn about", "linkedin.headline": "LinkedIn headline", "linkedin.profile_url": "LinkedIn URL", "linkedin.mutuals": "LinkedIn mutuals", "linkedin.partial": "LinkedIn coverage", "instagram.biography": "Instagram bio", "instagram.followers_count": "Instagram followers", "instagram.followees_count": "Instagram following", "instagram.media_count": "Instagram posts", "instagram.profile_pic_url": "Instagram avatar URL" }; return labels[fieldKey] || fieldKey.replace(/^monica\.|^Monica · /, "").replace(/[._]/g, " · "); }
function expandedFields(fields: Field[]): Field[] { const expanded: Field[] = []; for (const field of fields) { if (field.field_key !== "monica.custom_fields" || !field.value || typeof field.value !== "object" || Array.isArray(field.value)) { expanded.push(field); continue; } for (const [key, value] of Object.entries(field.value as Record<string, unknown>)) expanded.push({ ...field, field_key: `Monica · ${key}`, value }); } return expanded; }
function FactCard({fact}:{fact:StructuredFact}){
 const item=(fact.value&&typeof fact.value==="object"?fact.value:{}) as Record<string,unknown>;
 const institution=fact.company_name||fact.school_name||textValue(item.company_name||item.school_name);
 const title=textValue(item.title||item.degree||item.position_title);
 const dates=[item.start_date,item.end_date||(item.is_current?"present":null)].filter(Boolean).join(" — ");
 return <article className="fact-card"><h3>{institution||title||"Archived experience"}</h3>{title&&<p>{title}</p>}{textValue(item.field_of_study)&&<p>{textValue(item.field_of_study)}</p>}<p className="muted">{dates}{item.location?` · ${textValue(item.location)}`:""}</p>{item.description?<details className="career-description"><summary>Experience details</summary><p>{textValue(item.description)}</p></details>:null}</article>;
}

function formatFactValue(value: unknown): string { if (value === null || value === undefined || value === "") return ""; if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return typeof value === "boolean" ? (value ? "Yes" : "No") : String(value); if (Array.isArray(value)) return value.map((item) => formatFactValue(item)).filter(Boolean).join("\n"); if (typeof value === "object") { const item = value as Record<string, unknown>; const title = item.title || item.position_title || item.degree || item.degree_name || item.name || item.institution_name || item.school_name; const period = [item.start_date || item.from_date || item.start, item.end_date || item.to_date || item.end].filter(Boolean).join(" — "); const location = item.location; const description = item.description; return [title, location, period, description].filter(Boolean).map((part) => String(part)).join(" · ") || "Details archived"; } return String(value); }

function distinctRelationships(rows:Relationship[]):Relationship[]{const map=new Map<string,Relationship>();for(const row of rows){const key=`${row.relationship_type}:${row.related_profile_id}`;const old=map.get(key);if(!old)map.set(key,row);else if(old.direction!==row.direction)old.direction="both";}return [...map.values()];}
function relationshipLabel(type:string){return ({wechat_contact_card_friend:"WeChat contact-card friend",friend:"Friend",colleague:"Colleague",family:"Family",member:"Group member",owner:"Group owner"} as Record<string,string>)[type]||type;}
