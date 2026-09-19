"use client";
import {useEffect,useState} from "react";
import {MonthlyChart} from "./monthly-chart";
type Summary={months:{month:string;total:number;sent:number;received:number}[];total:number;sent:number;received:number;first?:string;last?:string;snapshot_at?:string;active_months:number;peak?:{month:string;total:number};timezone:string};
export function ChatMonthly({profileId}:{profileId:string}){
 const [data,setData]=useState<Summary|null>(null),[error,setError]=useState(false),[attempt,setAttempt]=useState(0);
 useEffect(()=>{const abort=new AbortController();setData(null);setError(false);fetch(`/api/v1/profiles/${profileId}/chat-months`,{signal:abort.signal}).then(r=>{if(!r.ok)throw Error();return r.json()}).then(setData).catch(e=>{if(e.name!=='AbortError')setError(true)});return()=>abort.abort()},[profileId,attempt]);
 const date=(value?:string)=>value?new Date(value).toLocaleDateString('zh-CN',{timeZone:data?.timezone||'UTC'}):'未收录';
 return <section className="panel profile-card chat-monthly"><div className="panel-heading"><h2>微信私聊月度分布</h2>{data?.snapshot_at&&<small>统计截至 {date(data.snapshot_at)}</small>}</div>{error?<button className="button button-soft" onClick={()=>setAttempt(v=>v+1)}>重试聊天统计</button>:!data?<p role="status">正在读取月度统计…</p>:!data.months.length?<p className="muted">尚无这位联系人的私聊月度记录。</p>:<><div className="chat-overview-numbers"><div><b>{data.total.toLocaleString()}</b><span>全部私聊消息</span></div><div><b>{data.peak?.month}</b><span>高峰月 · {data.peak?.total.toLocaleString()} 条</span></div><div><b>{data.active_months}</b><span>有消息的月份</span></div><div><b>{date(data.last)}</b><span>最近联系</span></div></div>
 <MonthlyChart rows={data.months} label="每月聊天" stacked href={month=>`/profiles/${profileId}?tab=messages&month=${month}&timezone=${encodeURIComponent(data.timezone)}`}/>
 <div className="chat-direction-totals"><span>我发送 <b>{data.sent.toLocaleString()}</b></span><span>对方发送 <b>{data.received.toLocaleString()}</b></span><span>首次联系 {date(data.first)}</span></div>
 <details><summary>每月精确数据</summary><div className="monthly-table"><table><thead><tr><th>月份</th><th>我发送</th><th>对方发送</th><th>合计</th></tr></thead><tbody>{data.months.map(row=><tr key={row.month}><th>{row.month}</th><td>{row.sent.toLocaleString()}</td><td>{row.received.toLocaleString()}</td><td>{row.total.toLocaleString()}</td></tr>)}</tbody></table></div></details></>}
 </section>;
}
