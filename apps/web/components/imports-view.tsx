"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Database, RefreshCw, X } from "lucide-react";
import { apiFetch } from "../lib/api";
import { IdentityReview } from "./identity-review";

type Batch = { id: string; batch_id: string; source: string; stream: string; status: string; received_at: string; completed_at?: string; inserted_count: number; changed_count: number; unchanged_count: number; error_summary?: string };
type Audit = { sources: {source:string;stream:string;source_count:number;projected_count:number;excluded_count:number;stage:string;checked_at:string;details:unknown;missing_ids:unknown}[]; media:{state:string;count:number}[]; jobs:{job_type:string;status:string;count:number}[]; messages:{processed_tables:number;source_rows:number;processed_rows:number} };
const states:Record<string,string>={ready:"本地可用",pending:"等待下载",downloading:"下载中",expired:"来源已过期",unavailable:"来源不可用",failed:"处理失败",projected:"对象已投影",reconciled:"已对账"};
export function ImportsView(){
 const [batches,setBatches]=useState<Batch[]>([]);const [audit,setAudit]=useState<Audit|null>(null);
 const [loading,setLoading]=useState(true);const [error,setError]=useState("");
 const [selected,setSelected]=useState<Batch|null>(null);const [detail,setDetail]=useState<unknown>(null);const [replaying,setReplaying]=useState(false);
 const dialog=useRef<HTMLDialogElement>(null);
 const load=useCallback(async()=>{setLoading(true);try{
   const responses=await Promise.all([fetch('/api/v1/imports/batches'),fetch('/api/v1/imports/reconciliation')]);
   if(responses.some(r=>!r.ok))throw new Error();setBatches(await responses[0].json());setAudit(await responses[1].json());setError("");
 }catch{setError("暂时无法读取导入记录，请重试。");}finally{setLoading(false);}},[]);
 useEffect(()=>{void load();},[load]);
 async function open(batch:Batch){setSelected(batch);setDetail(null);dialog.current?.showModal();const r=await fetch(`/api/v1/imports/batches/${encodeURIComponent(batch.batch_id)}`);setDetail(r.ok?await r.json():{error:"无法读取批次"});}
 async function replay(){if(!selected)return;setReplaying(true);try{const r=await apiFetch(`/api/v1/imports/batches/${encodeURIComponent(selected.batch_id)}/replay`,{method:'POST'});setDetail(await r.json());await load();}finally{setReplaying(false);}}
 return <div className="page-wrap"><div className="page-heading"><div><p className="eyebrow">IMPORTS</p><h1>导入中心</h1><p className="muted">批次处理、来源覆盖和媒体可用性分别核对。批次完成不代表来源完整。</p></div><button className="button button-soft" onClick={()=>void load()}><RefreshCw size={16}/>刷新</button></div>
 {error&&<p role="alert">{error}</p>}<IdentityReview/>
 <section className="panel import-panel"><div className="panel-heading"><h2>来源对账</h2><Database size={18}/></div>{audit?.sources.length?audit.sources.map(s=><details className="reconciliation-row" key={`${s.source}:${s.stream}`}><summary><strong>{s.source} · {s.stream}</strong><span>源对象 {s.source_count.toLocaleString()} · 已投影 {s.projected_count.toLocaleString()} · 排除 {s.excluded_count.toLocaleString()}</span><span>{states[s.stage]||s.stage}</span></summary><p className="muted">核对时间：{formatDate(s.checked_at)}</p><pre>{JSON.stringify({details:s.details,missing:s.missing_ids},null,2)}</pre></details>):<p className="muted">尚无完整的来源对账记录。</p>}
 {audit&&<p className="muted">消息已核对 {audit.messages.processed_tables} 个源表，游标处理 {audit.messages.processed_rows.toLocaleString()} / {audit.messages.source_rows.toLocaleString()} 行。此分母只含已扫描的源表。</p>}</section>
 <section className="panel import-panel"><div className="panel-heading"><h2>媒体归档</h2></div><div className="principle-grid">{audit?.media.map(m=><div className="principle" key={m.state}><div><strong>{states[m.state]||m.state}</strong><p>{m.count.toLocaleString()} 个来源引用</p></div></div>)}</div><p className="muted">过期链接保留来源和失败原因，已有图片不会因为一次失败而被删除。</p></section>
 <section className="panel import-panel"><div className="panel-heading"><h2>最近批次</h2><span className="muted">未变化内容只增加观察记录</span></div>{loading?<p role="status">正在读取…</p>:batches.map(b=><div className="import-row" key={b.id}><Database size={16}/><div><strong>{b.source} · {b.stream}</strong><small>{b.inserted_count} 新增 · {b.changed_count} 变化 · {b.unchanged_count} 未变化</small></div><span>{b.status==='complete'?'批次已处理':b.status}</span><time>{formatDate(b.completed_at||b.received_at)}</time><button className="button button-soft" onClick={()=>void open(b)}>查看</button></div>)}</section>
 <dialog className="photo-dialog import-dialog" ref={dialog} aria-label="批次审计"><button className="dialog-close" aria-label="关闭批次审计" onClick={()=>dialog.current?.close()}><X/></button><h2>批次审计</h2><p>{selected?.batch_id}</p><pre>{detail?JSON.stringify(detail,null,2):'正在读取…'}</pre><button className="button button-soft" disabled={replaying||!detail} onClick={()=>void replay()}>{replaying?'重放中…':'幂等重放此批次'}</button></dialog></div>;
}
function formatDate(value:string){return new Intl.DateTimeFormat('zh-CN',{dateStyle:'medium',timeStyle:'short'}).format(new Date(value));}
