"use client";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
type Result={id:string;entity_type:string;title:string;summary:string};
export function SearchView(){
 const params=useSearchParams(),query=params.get('q')||'';
 const [rows,setRows]=useState<Result[]>([]),[busy,setBusy]=useState(false),[error,setError]=useState('');
 useEffect(()=>{const abort=new AbortController();setBusy(true);setError('');fetch(`/api/v1/search?q=${encodeURIComponent(query)}`,{signal:abort.signal}).then(async r=>{if(!r.ok)throw new Error();setRows(await r.json());}).catch(e=>{if(e.name!=='AbortError')setError('搜索暂时不可用，请重试。');}).finally(()=>{if(!abort.signal.aborted)setBusy(false)});return()=>abort.abort()},[query]);
 const href=(row:Result)=>row.entity_type==='profile'?`/profiles/${row.id}`:row.entity_type==='tag'?`/profiles?tag=${row.id}`:`/dashboard?event=${row.id}`;
 const label:Record<string,string>={profile:'联系人',tag:'分类',timeline:'社交动态',activity:'活动与记录'};
 return <div className="page-wrap"><div className="page-heading"><div><h1>搜索“{query}”</h1><p className="muted">联系人、分类和社交动态。聊天正文在对应会话内搜索。</p></div></div>{busy?<p role="status">正在搜索…</p>:error?<p role="alert">{error}</p>:rows.length?<section className="profile-list">{rows.map(row=><Link className="profile-list-row" href={href(row)} key={`${row.entity_type}:${row.id}`}><span className="profile-list-main"><strong>{row.title}</strong><small>{summary(row.summary)}</small></span><span className="profile-type">{label[row.entity_type]}</span></Link>)}</section>:<p>没有符合条件的结果。</p>}</div>;
}
function summary(value:string){try{const parsed=JSON.parse(value);return typeof parsed==='object'?String(parsed?.text||parsed?.caption||parsed?.body||''):value}catch{return value}}
