"use client";
import {useEffect,useRef,useState} from "react";
import Link from "next/link";
import {useSearchParams} from "next/navigation";
import {LoadMore} from "./load-more";
type Message={id:string;occurred_at:string;message_type:string;text?:string;sender_profile_id?:string;sender_name?:string};
export function ConversationView({profileId,conversationId}:{profileId?:string;conversationId?:string}) {
 const searchParams=useSearchParams();const month=searchParams.get("month"),timezone=searchParams.get("timezone")||"UTC";
 const [rows,setRows]=useState<Message[]>([]),[query,setQuery]=useState(""),[busy,setBusy]=useState(false),[error,setError]=useState("");
 const request=useRef<AbortController|null>(null);
 const [hasMore,setHasMore]=useState(false);
 const activeQuery=useRef("");
 async function load(more=false,search=query){
  if(more&&busy)return;
  if(!more)activeQuery.current=search;else search=activeQuery.current;
  request.current?.abort();const abort=new AbortController();request.current=abort;setBusy(true);setError("");
  const params=new URLSearchParams({limit:"50"});if(search)params.set("q",search);if(month){params.set("month",month);params.set("timezone",timezone)}
  const last=rows.at(-1);if(more&&last){params.set("before",last.occurred_at);params.set("before_id",last.id)}
  try{
   const response=await fetch(`/api/v1/${conversationId?`conversations/${conversationId}`:`profiles/${profileId}`}/messages?${params}`,{signal:abort.signal});
   if(!response.ok)throw new Error();const next=await response.json();
   if(!abort.signal.aborted){setRows(previous=>more?[...previous,...next.filter((row:Message)=>!previous.some(old=>old.id===row.id))]:next);setHasMore(next.length===50);}
  }catch{if(!abort.signal.aborted)setError("Could not load chat history. Try again.")}
  finally{if(!abort.signal.aborted)setBusy(false)}
 }
 useEffect(()=>{setRows([]);setQuery("");void load(false,"");return()=>request.current?.abort()},[profileId,conversationId,month,timezone]);
 return <section className="panel profile-card"><h2>Chat history</h2><p className="muted">Search only this person's or group's conversation. Messages are not included in global search.</p>{month&&<div className="message-month-filter"><strong>Chat in {month}</strong><span>{timezone}</span><Link href={profileId?`/profiles/${profileId}?tab=messages`:`/messages?conversation=${conversationId}`}>View all months</Link></div>}<form className="message-search" onSubmit={e=>{e.preventDefault();void load()}}><label htmlFor="message-query">Search this conversation</label><input id="message-query" type="search" value={query} onChange={e=>setQuery(e.target.value)} placeholder="Keywords…"/><button className="button button-soft">Search</button></form>{error&&<p role="alert">{error}</p>}<div className="message-list">{rows.map(row=><article key={row.id}><header>{row.sender_profile_id?<Link href={`/profiles/${row.sender_profile_id}`}>{row.sender_name||"Person"}</Link>:<span>Sender not linked</span>}<time>{new Intl.DateTimeFormat('en-US',{dateStyle:'medium',timeStyle:'short'}).format(new Date(row.occurred_at))}</time></header><p>{readable(row)}</p></article>)}</div>{!busy&&!rows.length&&<p>No matching archived messages.</p>}{busy&&<p role="status">Loading…</p>}{hasMore&&<LoadMore cursor={rows.at(-1)?.id||""} busy={busy} error={!!error} onLoad={()=>void load(true)} label="Earlier messages"/>}</section>
}
function readable(row:Message){if(row.message_type==='1')return row.text||"Empty message";const names:Record<string,string>={'3':'Image','34':'Voice','43':'Video','47':'Sticker','49':'Share','10000':'System message'};if(row.text?.startsWith('<')){const doc=new DOMParser().parseFromString(row.text,'text/xml');return doc.querySelector('title')?.textContent||doc.querySelector('content')?.textContent||`[${names[row.message_type]||'Message'}]`}return row.text||`[${names[row.message_type]||'Message'}]`}
