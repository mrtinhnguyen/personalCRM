"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Database, RefreshCw, X } from "lucide-react";
import { apiFetch } from "../lib/api";
import { IdentityReview } from "./identity-review";

type Batch = { id: string; batch_id: string; source: string; stream: string; status: string; received_at: string; completed_at?: string; inserted_count: number; changed_count: number; unchanged_count: number; error_summary?: string };
type Audit = { sources: {source:string;stream:string;source_count:number;projected_count:number;excluded_count:number;stage:string;checked_at:string;details:unknown;missing_ids:unknown}[]; media:{state:string;count:number}[]; jobs:{job_type:string;status:string;count:number}[]; messages:{processed_tables:number;source_rows:number;processed_rows:number} };
const states:Record<string,string>={ready:"Available locally",pending:"Waiting to download",downloading:"Downloading",expired:"Source expired",unavailable:"Source unavailable",failed:"Processing failed",projected:"Projected",reconciled:"Reconciled"};
export function ImportsView(){
 const [batches,setBatches]=useState<Batch[]>([]);const [audit,setAudit]=useState<Audit|null>(null);
 const [loading,setLoading]=useState(true);const [error,setError]=useState("");
 const [selected,setSelected]=useState<Batch|null>(null);const [detail,setDetail]=useState<unknown>(null);const [replaying,setReplaying]=useState(false);
 const dialog=useRef<HTMLDialogElement>(null);
 const load=useCallback(async()=>{setLoading(true);try{
   const responses=await Promise.all([fetch('/api/v1/imports/batches'),fetch('/api/v1/imports/reconciliation')]);
   if(responses.some(r=>!r.ok))throw new Error();setBatches(await responses[0].json());setAudit(await responses[1].json());setError("");
 }catch{setError("Could not load import records. Try again.");}finally{setLoading(false);}},[]);
 useEffect(()=>{void load();},[load]);
 async function open(batch:Batch){setSelected(batch);setDetail(null);dialog.current?.showModal();const r=await fetch(`/api/v1/imports/batches/${encodeURIComponent(batch.batch_id)}`);setDetail(r.ok?await r.json():{error:"Could not load this batch"});}
 async function replay(){if(!selected)return;setReplaying(true);try{const r=await apiFetch(`/api/v1/imports/batches/${encodeURIComponent(selected.batch_id)}/replay`,{method:'POST'});setDetail(await r.json());await load();}finally{setReplaying(false);}}
 return <div className="page-wrap"><div className="page-heading"><div><p className="eyebrow">IMPORTS</p><h1>Import center</h1><p className="muted">Batches, source coverage, and media availability are checked separately. A finished batch does not mean the source is complete.</p></div><button className="button button-soft" onClick={()=>void load()}><RefreshCw size={16}/>Refresh</button></div>
 {error&&<p role="alert">{error}</p>}<IdentityReview/>
 <section className="panel import-panel"><div className="panel-heading"><h2>Source reconciliation</h2><Database size={18}/></div>{audit?.sources.length?audit.sources.map(s=><details className="reconciliation-row" key={`${s.source}:${s.stream}`}><summary><strong>{s.source} · {s.stream}</strong><span>Source objects {s.source_count.toLocaleString()} · projected {s.projected_count.toLocaleString()} · excluded {s.excluded_count.toLocaleString()}</span><span>{states[s.stage]||s.stage}</span></summary><p className="muted">Checked: {formatDate(s.checked_at)}</p><pre>{JSON.stringify({details:s.details,missing:s.missing_ids},null,2)}</pre></details>):<p className="muted">No complete source reconciliation records yet.</p>}
 {audit&&<p className="muted">Messages checked across {audit.messages.processed_tables} source tables; cursor processed {audit.messages.processed_rows.toLocaleString()} / {audit.messages.source_rows.toLocaleString()} rows. The denominator only includes scanned source tables.</p>}</section>
 <section className="panel import-panel"><div className="panel-heading"><h2>Media archive</h2></div><div className="principle-grid">{audit?.media.map(m=><div className="principle" key={m.state}><div><strong>{states[m.state]||m.state}</strong><p>{m.count.toLocaleString()} source references</p></div></div>)}</div><p className="muted">Expired links keep the source and failure reason. Existing images are not deleted because of a single failure.</p></section>
 <section className="panel import-panel"><div className="panel-heading"><h2>Recent batches</h2><span className="muted">Unchanged content only adds an observation</span></div>{loading?<p role="status">Loading…</p>:batches.map(b=><div className="import-row" key={b.id}><Database size={16}/><div><strong>{b.source} · {b.stream}</strong><small>{b.inserted_count} inserted · {b.changed_count} changed · {b.unchanged_count} unchanged</small></div><span>{b.status==='complete'?'Batch processed':b.status}</span><time>{formatDate(b.completed_at||b.received_at)}</time><button className="button button-soft" onClick={()=>void open(b)}>View</button></div>)}</section>
 <dialog className="photo-dialog import-dialog" ref={dialog} aria-label="Batch audit"><button className="dialog-close" aria-label="Close batch audit" onClick={()=>dialog.current?.close()}><X/></button><h2>Batch audit</h2><p>{selected?.batch_id}</p><pre>{detail?JSON.stringify(detail,null,2):'Loading…'}</pre><button className="button button-soft" disabled={replaying||!detail} onClick={()=>void replay()}>{replaying?'Replaying…':'Replay this batch idempotently'}</button></dialog></div>;
}
function formatDate(value:string){return new Intl.DateTimeFormat('en-US',{dateStyle:'medium',timeStyle:'short'}).format(new Date(value));}
