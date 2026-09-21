"use client";
import {useEffect,useState} from "react";
import {MonthlyChart} from "./monthly-chart";
type Summary={months:{month:string;total:number;sent:number;received:number}[];total:number;sent:number;received:number;first?:string;last?:string;snapshot_at?:string;active_months:number;peak?:{month:string;total:number};timezone:string};
export function ChatMonthly({profileId}:{profileId:string}){
 const [data,setData]=useState<Summary|null>(null),[error,setError]=useState(false),[attempt,setAttempt]=useState(0);
 useEffect(()=>{const abort=new AbortController();setData(null);setError(false);fetch(`/api/v1/profiles/${profileId}/chat-months`,{signal:abort.signal}).then(r=>{if(!r.ok)throw Error();return r.json()}).then(setData).catch(e=>{if(e.name!=='AbortError')setError(true)});return()=>abort.abort()},[profileId,attempt]);
 const date=(value?:string)=>value?new Date(value).toLocaleDateString('en-US',{timeZone:data?.timezone||'UTC'}):'Not archived';
 return <section className="panel profile-card chat-monthly"><div className="panel-heading"><h2>WeChat private chat by month</h2>{data?.snapshot_at&&<small>Counted through {date(data.snapshot_at)}</small>}</div>{error?<button className="button button-soft" onClick={()=>setAttempt(v=>v+1)}>Retry chat statistics</button>:!data?<p role="status">Loading monthly statistics…</p>:!data.months.length?<p className="muted">No monthly private-chat records for this person yet.</p>:<><div className="chat-overview-numbers"><div><b>{data.total.toLocaleString()}</b><span>All private messages</span></div><div><b>{data.peak?.month}</b><span>Peak month · {data.peak?.total.toLocaleString()} messages</span></div><div><b>{data.active_months}</b><span>Months with messages</span></div><div><b>{date(data.last)}</b><span>Last contact</span></div></div>
 <MonthlyChart rows={data.months} label="Chat per month" stacked href={month=>`/profiles/${profileId}?tab=messages&month=${month}&timezone=${encodeURIComponent(data.timezone)}`}/>
 <div className="chat-direction-totals"><span>I sent <b>{data.sent.toLocaleString()}</b></span><span>They sent <b>{data.received.toLocaleString()}</b></span><span>First contact {date(data.first)}</span></div>
 <details><summary>Exact monthly counts</summary><div className="monthly-table"><table><thead><tr><th>Month</th><th>I sent</th><th>They sent</th><th>Total</th></tr></thead><tbody>{data.months.map(row=><tr key={row.month}><th>{row.month}</th><td>{row.sent.toLocaleString()}</td><td>{row.received.toLocaleString()}</td><td>{row.total.toLocaleString()}</td></tr>)}</tbody></table></div></details></>}
 </section>;
}
