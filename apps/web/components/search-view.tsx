"use client";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
type Result={id:string;entity_type:string;title:string;summary:string};
export function SearchView(){
 const params=useSearchParams(),query=params.get('q')||'';
 const [rows,setRows]=useState<Result[]>([]),[busy,setBusy]=useState(false),[error,setError]=useState('');
 useEffect(()=>{const abort=new AbortController();setBusy(true);setError('');fetch(`/api/v1/search?q=${encodeURIComponent(query)}`,{signal:abort.signal}).then(async r=>{if(!r.ok)throw new Error();setRows(await r.json());}).catch(e=>{if(e.name!=='AbortError')setError('Search is unavailable. Try again.');}).finally(()=>{if(!abort.signal.aborted)setBusy(false)});return()=>abort.abort()},[query]);
 const href=(row:Result)=>row.entity_type==='profile'?`/profiles/${row.id}`:row.entity_type==='tag'?`/profiles?tag=${row.id}`:`/dashboard?event=${row.id}`;
 const label:Record<string,string>={profile:'People',tag:'Tags',timeline:'Posts',activity:'Notes'};
 return <div className="page-wrap"><div className="page-heading"><div><h1>Search “{query}”</h1><p className="muted">People, tags, and posts. Message text is searched inside each conversation.</p></div></div>{busy?<p role="status">Searching…</p>:error?<p role="alert">{error}</p>:rows.length?<section className="profile-list">{rows.map(row=><Link className="profile-list-row" href={href(row)} key={`${row.entity_type}:${row.id}`}><span className="profile-list-main"><strong>{row.title}</strong><small>{summary(row.summary)}</small></span><span className="profile-type">{label[row.entity_type]}</span></Link>)}</section>:<p>No matching results.</p>}</div>;
}
function summary(value:string){try{const parsed=JSON.parse(value);return typeof parsed==='object'?String(parsed?.text||parsed?.caption||parsed?.body||''):value}catch{return value}}
