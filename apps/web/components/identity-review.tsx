"use client";
import Link from "next/link";
import {useEffect,useState} from "react";
import {apiFetch} from "../lib/api";
type Candidate={id:string;provider:string;external_id:string;username?:string;source_profile_id:string;candidate_profile_id:string;candidate_display_name:string;evidence:unknown};
export function IdentityReview(){
 const [rows,setRows]=useState<Candidate[]>([]),[confirming,setConfirming]=useState<string|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState("");
 async function load(){const r=await fetch('/api/v1/identity-candidates');if(r.ok)setRows(await r.json());else setError("无法读取匹配候选。");}
 useEffect(()=>{void load();},[]);
 async function decide(row:Candidate,action:'accept'|'reject'){setBusy(true);setError("");try{const r=await apiFetch(`/api/v1/identity-candidates/${row.id}/${action}`,{method:'POST'});if(!r.ok)throw new Error();setConfirming(null);await load();}catch{setError("审核未保存，请检查候选资料后重试。");}finally{setBusy(false);}}
 return <section className="panel import-panel"><div className="panel-heading"><h2>身份匹配待审核</h2></div><p className="muted">确认同一人后才移动账号、动态和关系。姓名相同不会触发自动合并。</p>{error&&<p role="alert">{error}</p>}{!rows.length&&<p className="muted">当前没有待审核候选。独立来源账号继续保持独立。</p>}{rows.map(row=><article className="candidate-card" key={row.id}><p><Link href={`/profiles/${row.source_profile_id}`}>{row.provider} · {row.username||row.external_id}</Link><span> → </span><Link href={`/profiles/${row.candidate_profile_id}`}>{row.candidate_display_name}</Link></p><details><summary>查看来源证据</summary><pre>{JSON.stringify(row.evidence,null,2)}</pre></details>{confirming===row.id?<div><p>确认这两个资料属于同一个人，并将来源资料合并到「{row.candidate_display_name}」？</p><button className="button button-primary" disabled={busy} onClick={()=>void decide(row,'accept')}>确认合并</button><button className="button button-soft" onClick={()=>setConfirming(null)}>取消</button></div>:<div className="edit-panel-actions"><button className="button button-soft" disabled={busy} onClick={()=>void decide(row,'reject')}>不是同一人</button><button className="button button-primary" disabled={busy} onClick={()=>setConfirming(row.id)}>审核并确认</button></div>}</article>)}</section>;
}
