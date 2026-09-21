"use client";

import Link from "next/link";
import {useSearchParams,useRouter} from "next/navigation";
import {TagFilter} from "./tag-filter";
import { Search, Users, UserRound, UsersRound } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import {LoadMore} from "./load-more";
import { apiFetch } from "../lib/api";

type Profile = { id: string; profile_type: "person" | "group"; display_name: string; avatar_media_id?: string | null; summary?: string | null };

export function ProfilesView() {
  const searchParams=useSearchParams(),router=useRouter();const selectedTag=searchParams.get("tag")||"";
  const request=useRef<AbortController|null>(null);
  const [error,setError]=useState("");
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [filter, setFilter] = useState("all");
  const [more, setMore] = useState(false);
  const [busy, setBusy] = useState(false);
  const [query, setQuery] = useState("");
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [profileType, setProfileType] = useState<"person" | "group">("person");
  const [summary, setSummary] = useState("");
  useEffect(() => { const params = new URLSearchParams(window.location.search); setQuery(params.get("search") || ""); setFilter(params.get("type") || "all"); }, []);
  async function load(cursor?: string) {
    if(cursor&&busy)return;
    request.current?.abort();const abort=new AbortController();request.current=abort;
    setBusy(true);setError("");
    const params = new URLSearchParams(window.location.search);
    params.set("limit", "48"); params.set("q",query);
    if (filter !== "all") params.set("profile_type",filter);else params.delete("profile_type");
    if (cursor) params.set("cursor",cursor);else params.delete("cursor");
    try { const response = await fetch(`/api/v1/profiles?${params}`,{signal:abort.signal}); if (!response.ok) throw new Error(); const rows: Profile[] = await response.json();if(abort.signal.aborted)return;setProfiles(previous => cursor ? [...previous,...rows.filter(row=>!previous.some(old=>old.id===row.id))] : rows);setMore(rows.length===48); }
    catch{if(!abort.signal.aborted)setError("Could not load people. Try again.");}
    finally { if(!abort.signal.aborted)setBusy(false); }
  }
  useEffect(() => {setMore(false);setBusy(true);const timeout = setTimeout(() => {setProfiles([]);void load();},250);return()=>{clearTimeout(timeout);request.current?.abort();};},[query,filter,selectedTag]);
  async function createProfile() {
    const response = await apiFetch("/api/v1/profiles", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ display_name: name, profile_type: profileType, summary: summary || null }) });
    if (response.ok) { const profile = await response.json(); setProfiles((items) => [profile, ...items]); setName(""); setSummary(""); setCreating(false); }
  }
  return <div className="page-wrap"><div className="page-heading"><div><h1>People</h1><p className="muted">The people you know, and the groups you share.</p></div><button className="button button-primary" onClick={() => setCreating((value) => !value)}><Users size={16} />{creating ? "Close" : "New person"}</button></div>{creating && <section className="panel create-panel"><div className="create-panel-fields"><label>Name<input value={name} onChange={(event) => setName(event.target.value)} placeholder="For example, Alex Chen" /></label><label>Type<select value={profileType} onChange={(event) => setProfileType(event.target.value as "person" | "group")}><option value="person">Person</option><option value="group">Group</option></select></label><label className="create-summary">Summary<input value={summary} onChange={(event) => setSummary(event.target.value)} placeholder="Optional" /></label></div><button className="button button-primary" disabled={!name.trim()} onClick={() => void createProfile()}>Create</button></section>}<div className="profile-toolbar"><label className="local-search"><Search size={16} /><input value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Search people" placeholder="Search names, notes, or summaries…" /></label><div className="list-filters">{[["all","All"],["person","People"],["group","Groups"]].map(([key,label]) => <button className={filter === key ? "selected" : ""} onClick={() => setFilter(key)} key={key}>{label}</button>)}</div></div><TagFilter profileType={filter} selected={selectedTag} onSelect={id=>{const params=new URLSearchParams(searchParams.toString());if(id)params.set("tag",id);else params.delete("tag");router.replace(`/profiles?${params}`,{scroll:false});}}/><section className="profile-list">{profiles.length ? profiles.map((profile) => <Link href={`/profiles/${profile.id}`} className="profile-list-row" key={profile.id}><span className={`list-avatar ${profile.profile_type}`}>{profile.avatar_media_id ? <img src={`/api/v1/media/${profile.avatar_media_id}`} width={52} height={52} alt="" loading="lazy"/> : profile.profile_type === "group" ? <UsersRound size={17} /> : <UserRound size={17} />}</span><span className="profile-list-main"><strong>{profile.display_name}</strong><small>{profile.summary || (profile.profile_type === "group" ? "Group" : "No summary yet")}</small></span><span className="profile-type">{profile.profile_type === "group" ? "Group" : "Person"}</span></Link>) : <div className="empty-state"><Users size={22} /><strong>{busy?"Looking up people…":"No people match these filters"}</strong><span>{selectedTag?"Clear the tag or switch between people and groups.":"Try a different search or type."}</span></div>}</section>{error&&<p role="alert">{error}{!more&&<button className="button button-soft" onClick={()=>void load()}>Retry</button>}</p>}{more&&<LoadMore cursor={profiles.at(-1)?.id||""} busy={busy} error={!!error} onLoad={()=>void load(profiles.at(-1)?.id)} label="Load more people"/>}</div>;
}
