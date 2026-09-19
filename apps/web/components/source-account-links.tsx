"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Link2, Unlink, X } from "lucide-react";
import { apiFetch } from "../lib/api";

type Account = {id:string;provider:string;external_id:string;object_kind:string;display_name:string;username?:string;ready:boolean;profile_id:string|null;linked_profile_name?:string};
const labels:Record<string,string>={wechat:"微信",instagram:"Instagram",linkedin:"LinkedIn"};
async function readAccounts(url:string,signal:AbortSignal):Promise<Account[]>{const response=await apiFetch(url,{signal});if(!response.ok)throw new Error("Account request failed");return response.json();}

export function SourceAccountLinks({profileId,profileType,onChanged}:{profileId:string;profileType:string;onChanged:()=>void}) {
  const [open,setOpen]=useState(false),[accounts,setAccounts]=useState<Account[]>([]),[results,setResults]=useState<Account[]>([]);
  const [query,setQuery]=useState(""),[provider,setProvider]=useState("wechat"),[pending,setPending]=useState<{account:Account;unlink:boolean}|null>(null);
  const [busy,setBusy]=useState(false),[error,setError]=useState(""),[revision,setRevision]=useState(0);
  const dialog=useRef<HTMLDivElement>(null);
  useEffect(()=>{
    if(!open)return;
    const abort=new AbortController();setError("");
    readAccounts(`/api/v1/source-accounts?profile_id=${profileId}`,abort.signal).then(setAccounts).catch(()=>{if(!abort.signal.aborted)setError("暂时无法读取账号。");});
    return()=>abort.abort();
  },[open,profileId,revision]);
  useEffect(()=>{
    setResults([]);if(!open||!query.trim())return;
    const abort=new AbortController();const timer=setTimeout(()=>{
      readAccounts(`/api/v1/source-accounts?provider=${provider}&q=${encodeURIComponent(query.trim())}`,abort.signal)
        .then(rows=>setResults(rows.filter(row=>row.object_kind===profileType&&row.profile_id!==profileId)))
        .catch(()=>{if(!abort.signal.aborted)setError("搜索失败，请重试。");});
    },250);
    return()=>{clearTimeout(timer);abort.abort();};
  },[open,query,provider,profileId,profileType,revision]);
  useEffect(()=>{if(!open)return;const escape=(event:KeyboardEvent)=>{if(event.key==="Escape"&&!busy){setOpen(false);setPending(null);}};window.addEventListener("keydown",escape);return()=>window.removeEventListener("keydown",escape);},[open,busy]);
  useEffect(()=>{if(!open)return;const before=document.activeElement as HTMLElement|null;const old=document.body.style.overflow;document.body.style.overflow="hidden";dialog.current?.querySelector<HTMLButtonElement>("button")?.focus();const trap=(event:KeyboardEvent)=>{if(event.key!=="Tab")return;const nodes=Array.from(dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled),a[href],input,select')||[]);const first=nodes[0],last=nodes.at(-1);if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}};document.addEventListener("keydown",trap);return()=>{document.body.style.overflow=old;document.removeEventListener("keydown",trap);before?.focus();};},[open]);
  async function save(){
    if(!pending)return;setBusy(true);setError("");
    try{
      const response=await apiFetch(`/api/v1/source-accounts/${pending.account.id}/link`,{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({profile_id:pending.unlink?null:profileId,expected_profile_id:pending.account.profile_id})});
      if(!response.ok)throw new Error("Link not saved");
      setPending(null);setRevision(n=>n+1);onChanged();
    }catch{setError("关联未保存。请刷新核对当前归属；来源资料会完整保留。");}finally{setBusy(false);}
  }
  function row(account:Account,unlink:boolean){return <li key={account.id}><div><strong>{labels[account.provider]} · {account.display_name}</strong><small>{account.username||account.external_id}</small>{account.profile_id&&!unlink&&<small>当前关联 <Link href={`/profiles/${account.profile_id}`}>{account.linked_profile_name}</Link></small>}</div><button className="button button-soft" disabled={!account.ready||busy} onClick={()=>setPending({account,unlink})}>{account.ready?<>{unlink?<Unlink size={14}/>:<Link2 size={14}/>}{unlink?"解除关联":"关联"}</>:"来源核对中"}</button></li>;}
  return <><button className="button button-soft" onClick={()=>setOpen(true)}><Link2 size={15}/>管理来源账号</button>{open&&<div ref={dialog} className="account-dialog-backdrop" onClick={event=>{if(event.target===event.currentTarget&&!busy)setOpen(false);}}><section className="account-dialog" role="dialog" aria-modal="true" aria-labelledby="account-dialog-title"><div className="panel-heading"><h2 id="account-dialog-title">来源账号</h2><button className="button button-ghost" aria-label="关闭来源账号" disabled={busy} onClick={()=>setOpen(false)}><X size={20}/></button></div><p className="muted">每个平台独立保存资料、动态和历史。关联决定此页显示哪些账号，解除后仍可重新关联。</p>{error&&<p role="alert">{error}</p>}{pending?<div className="account-confirm"><h3>{pending.unlink?"解除此账号关联":"确认账号归属"}</h3><p>{labels[pending.account.provider]} · {pending.account.display_name} · {pending.account.username||pending.account.external_id}</p><p>{pending.unlink?"此人物页将不再显示这个账号的内容。人物的手工资料和记录会保留。":pending.account.profile_id?`此账号将从「${pending.account.linked_profile_name}」解除，并关联到当前人物。` :"确认这个来源账号属于当前人物后关联。"}</p><div className="button-row"><button className="button button-primary" disabled={busy} onClick={()=>void save()}>{busy?"保存中…":"确认"}</button><button className="button button-soft" disabled={busy} onClick={()=>setPending(null)}>取消</button></div></div>:<><ul className="account-list">{accounts.map(account=>row(account,true))}</ul>{!accounts.length&&<p className="muted">当前没有关联来源账号。</p>}<form className="account-search" onSubmit={event=>event.preventDefault()}><label>平台<select value={provider} onChange={event=>setProvider(event.target.value)}>{Object.entries(labels).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label><label>寻找已有账号<input value={query} onChange={event=>setQuery(event.target.value)} placeholder="账号 ID、用户名或显示名" autoComplete="off"/></label></form><ul className="account-list">{results.map(account=>row(account,false))}</ul></>}</section></div>}</>;
}
