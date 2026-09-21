"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Link2, Unlink, X } from "lucide-react";
import { apiFetch } from "../lib/api";

type Account = {id:string;provider:string;external_id:string;object_kind:string;display_name:string;username?:string;ready:boolean;profile_id:string|null;linked_profile_name?:string};
const labels:Record<string,string>={wechat:"WeChat",instagram:"Instagram",linkedin:"LinkedIn"};
async function readAccounts(url:string,signal:AbortSignal):Promise<Account[]>{const response=await apiFetch(url,{signal});if(!response.ok)throw new Error("Account request failed");return response.json();}

export function SourceAccountLinks({profileId,profileType,onChanged}:{profileId:string;profileType:string;onChanged:()=>void}) {
  const [open,setOpen]=useState(false),[accounts,setAccounts]=useState<Account[]>([]),[results,setResults]=useState<Account[]>([]);
  const [query,setQuery]=useState(""),[provider,setProvider]=useState("wechat"),[pending,setPending]=useState<{account:Account;unlink:boolean}|null>(null);
  const [busy,setBusy]=useState(false),[error,setError]=useState(""),[revision,setRevision]=useState(0);
  const dialog=useRef<HTMLDivElement>(null);
  useEffect(()=>{
    if(!open)return;
    const abort=new AbortController();setError("");
    readAccounts(`/api/v1/source-accounts?profile_id=${profileId}`,abort.signal).then(setAccounts).catch(()=>{if(!abort.signal.aborted)setError("Could not load accounts right now.");});
    return()=>abort.abort();
  },[open,profileId,revision]);
  useEffect(()=>{
    setResults([]);if(!open||!query.trim())return;
    const abort=new AbortController();const timer=setTimeout(()=>{
      readAccounts(`/api/v1/source-accounts?provider=${provider}&q=${encodeURIComponent(query.trim())}`,abort.signal)
        .then(rows=>setResults(rows.filter(row=>row.object_kind===profileType&&row.profile_id!==profileId)))
        .catch(()=>{if(!abort.signal.aborted)setError("Search failed. Try again.");});
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
    }catch{setError("The link was not saved. Refresh to check the current owner; source data is kept in full.");}finally{setBusy(false);}
  }
  function row(account:Account,unlink:boolean){return <li key={account.id}><div><strong>{labels[account.provider]} · {account.display_name}</strong><small>{account.username||account.external_id}</small>{account.profile_id&&!unlink&&<small>Currently linked to <Link href={`/profiles/${account.profile_id}`}>{account.linked_profile_name}</Link></small>}</div><button className="button button-soft" disabled={!account.ready||busy} onClick={()=>setPending({account,unlink})}>{account.ready?<>{unlink?<Unlink size={14}/>:<Link2 size={14}/>}{unlink?"Unlink":"Link"}</>:"Checking source"}</button></li>;}
  return <><button className="button button-soft" onClick={()=>setOpen(true)}><Link2 size={15}/>Manage source accounts</button>{open&&<div ref={dialog} className="account-dialog-backdrop" onClick={event=>{if(event.target===event.currentTarget&&!busy)setOpen(false);}}><section className="account-dialog" role="dialog" aria-modal="true" aria-labelledby="account-dialog-title"><div className="panel-heading"><h2 id="account-dialog-title">Source accounts</h2><button className="button button-ghost" aria-label="Close source accounts" disabled={busy} onClick={()=>setOpen(false)}><X size={20}/></button></div><p className="muted">Each platform keeps its own profile, posts, and history. Linking chooses which accounts this page shows. You can link them again after unlinking.</p>{error&&<p role="alert">{error}</p>}{pending?<div className="account-confirm"><h3>{pending.unlink?"Unlink this account":"Confirm this account belongs here"}</h3><p>{labels[pending.account.provider]} · {pending.account.display_name} · {pending.account.username||pending.account.external_id}</p><p>{pending.unlink?"This profile page will no longer show this account's content. Manual notes and records on the person are kept.":pending.account.profile_id?`This account will be unlinked from “${pending.account.linked_profile_name}” and linked to this person.` :"Confirm this source account belongs to this person, then link it."}</p><div className="button-row"><button className="button button-primary" disabled={busy} onClick={()=>void save()}>{busy?"Saving…":"Confirm"}</button><button className="button button-soft" disabled={busy} onClick={()=>setPending(null)}>Cancel</button></div></div>:<><ul className="account-list">{accounts.map(account=>row(account,true))}</ul>{!accounts.length&&<p className="muted">No source accounts linked yet.</p>}<form className="account-search" onSubmit={event=>event.preventDefault()}><label>Platform<select value={provider} onChange={event=>setProvider(event.target.value)}>{Object.entries(labels).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label><label>Find an existing account<input value={query} onChange={event=>setQuery(event.target.value)} placeholder="Account ID, username, or display name" autoComplete="off"/></label></form><ul className="account-list">{results.map(account=>row(account,false))}</ul></>}</section></div>}</>;
}
