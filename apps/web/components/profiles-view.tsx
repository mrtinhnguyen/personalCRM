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
    catch{if(!abort.signal.aborted)setError("联系人读取失败，请重试。");}
    finally { if(!abort.signal.aborted)setBusy(false); }
  }
  useEffect(() => {setMore(false);setBusy(true);const timeout = setTimeout(() => {setProfiles([]);void load();},250);return()=>{clearTimeout(timeout);request.current?.abort();};},[query,filter,selectedTag]);
  async function createProfile() {
    const response = await apiFetch("/api/v1/profiles", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ display_name: name, profile_type: profileType, summary: summary || null }) });
    if (response.ok) { const profile = await response.json(); setProfiles((items) => [profile, ...items]); setName(""); setSummary(""); setCreating(false); }
  }
  return <div className="page-wrap"><div className="page-heading"><div><h1>联系人</h1><p className="muted">熟悉的人与共同的圈子。</p></div><button className="button button-primary" onClick={() => setCreating((value) => !value)}><Users size={16} />{creating ? "关闭" : "新建联系人"}</button></div>{creating && <section className="panel create-panel"><div className="create-panel-fields"><label>名称<input value={name} onChange={(event) => setName(event.target.value)} placeholder="例如 Alex Chen" /></label><label>类型<select value={profileType} onChange={(event) => setProfileType(event.target.value as "person" | "group")}><option value="person">个人</option><option value="group">群组</option></select></label><label className="create-summary">摘要<input value={summary} onChange={(event) => setSummary(event.target.value)} placeholder="可选" /></label></div><button className="button button-primary" disabled={!name.trim()} onClick={() => void createProfile()}>创建联系人</button></section>}<div className="profile-toolbar"><label className="local-search"><Search size={16} /><input value={query} onChange={(e) => setQuery(e.target.value)} aria-label="搜索联系人" placeholder="搜索姓名、备注或摘要…" /></label><div className="list-filters">{[["all","全部"],["person","个人"],["group","群组"]].map(([key,label]) => <button className={filter === key ? "selected" : ""} onClick={() => setFilter(key)} key={key}>{label}</button>)}</div></div><TagFilter profileType={filter} selected={selectedTag} onSelect={id=>{const params=new URLSearchParams(searchParams.toString());if(id)params.set("tag",id);else params.delete("tag");router.replace(`/profiles?${params}`,{scroll:false});}}/><section className="profile-list">{profiles.length ? profiles.map((profile) => <Link href={`/profiles/${profile.id}`} className="profile-list-row" key={profile.id}><span className={`list-avatar ${profile.profile_type}`}>{profile.avatar_media_id ? <img src={`/api/v1/media/${profile.avatar_media_id}`} width={52} height={52} alt="" loading="lazy"/> : profile.profile_type === "group" ? <UsersRound size={17} /> : <UserRound size={17} />}</span><span className="profile-list-main"><strong>{profile.display_name}</strong><small>{profile.summary || (profile.profile_type === "group" ? "群组 Profile" : "尚未填写简介")}</small></span><span className="profile-type">{profile.profile_type === "group" ? "群组" : "个人"}</span></Link>) : <div className="empty-state"><Users size={22} /><strong>{busy?"正在查找联系人…":"没有符合筛选条件的联系人"}</strong><span>{selectedTag?"可以清除标签或切换人物类型。":"尝试调整搜索词或人物类型。"}</span></div>}</section>{error&&<p role="alert">{error}{!more&&<button className="button button-soft" onClick={()=>void load()}>重试</button>}</p>}{more&&<LoadMore cursor={profiles.at(-1)?.id||""} busy={busy} error={!!error} onLoad={()=>void load(profiles.at(-1)?.id)} label="加载更多联系人"/>}</div>;
}
