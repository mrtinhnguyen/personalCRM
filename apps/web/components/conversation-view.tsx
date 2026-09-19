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
  }catch{if(!abort.signal.aborted)setError("聊天记录读取失败，请重试。")}
  finally{if(!abort.signal.aborted)setBusy(false)}
 }
 useEffect(()=>{setRows([]);setQuery("");void load(false,"");return()=>request.current?.abort()},[profileId,conversationId,month,timezone]);
 return <section className="panel profile-card"><h2>聊天记录</h2><p className="muted">只搜索与此人或此群的会话。消息不会进入全局搜索。</p>{month&&<div className="message-month-filter"><strong>{month} 的聊天</strong><span>{timezone}</span><Link href={profileId?`/profiles/${profileId}?tab=messages`:`/messages?conversation=${conversationId}`}>查看所有月份</Link></div>}<form className="message-search" onSubmit={e=>{e.preventDefault();void load()}}><label htmlFor="message-query">会话内搜索</label><input id="message-query" type="search" value={query} onChange={e=>setQuery(e.target.value)} placeholder="关键词…"/><button className="button button-soft">搜索</button></form>{error&&<p role="alert">{error}</p>}<div className="message-list">{rows.map(row=><article key={row.id}><header>{row.sender_profile_id?<Link href={`/profiles/${row.sender_profile_id}`}>{row.sender_name||"联系人"}</Link>:<span>发送者未关联</span>}<time>{new Intl.DateTimeFormat('zh-CN',{dateStyle:'medium',timeStyle:'short'}).format(new Date(row.occurred_at))}</time></header><p>{readable(row)}</p></article>)}</div>{!busy&&!rows.length&&<p>尚无符合条件的已收录消息。</p>}{busy&&<p role="status">正在读取…</p>}{hasMore&&<LoadMore cursor={rows.at(-1)?.id||""} busy={busy} error={!!error} onLoad={()=>void load(true)} label="更早的消息"/>}</section>
}
function readable(row:Message){if(row.message_type==='1')return row.text||"空消息";const names:Record<string,string>={'3':'图片','34':'语音','43':'视频','47':'表情','49':'分享','10000':'系统消息'};if(row.text?.startsWith('<')){const doc=new DOMParser().parseFromString(row.text,'text/xml');return doc.querySelector('title')?.textContent||doc.querySelector('content')?.textContent||`[${names[row.message_type]||'消息'}]`}return row.text||`[${names[row.message_type]||'消息'}]`}
