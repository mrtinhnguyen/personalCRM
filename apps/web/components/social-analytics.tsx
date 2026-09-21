"use client";
import Link from 'next/link';
import {useEffect,useState,useMemo} from 'react';
import {MonthlyChart} from "./monthly-chart";
type Row={name:string;count?:number;value?:number;profile_id:string;posts?:number};
type Stats={people:number;authors:number;posts:number;likes:number;comments:number;local_photo_posts:number;first?:string;latest?:string;groups?:number;indexed_messages?:number;conversations?:number;monthly:{month:string;count:number}[];leaders:Row[];charts:{title:string;rows:Row[];denominator:number;filter?:string}[];chat?:{contacts:number;messages:number;sent:number;received:number;leaders:Row[];group_leaders:Row[]}};
const labels:Record<string,string>={wechat:'WeChat',instagram:'Instagram',linkedin:'LinkedIn'};
const n=(v:number|undefined)=>v==null?'—':v.toLocaleString('en-US');
export function SocialAnalytics({profileId}:{profileId?:string}){
 const [attempt,setAttempt]=useState(0);
 const [data,setData]=useState<{providers:Record<string,Stats>;as_of:string;scope:string}|null>(null),[source,setSource]=useState('wechat'),[error,setError]=useState(false);
 useEffect(()=>{const abort=new AbortController();setData(null);setError(false);fetch(`/api/v1/metrics/social${profileId?`?profile_id=${profileId}`:''}`,{signal:abort.signal}).then(r=>{if(!r.ok)throw Error();return r.json();}).then(setData).catch(e=>{if(e.name!=='AbortError')setError(true);});return()=>abort.abort();},[profileId,attempt]);
 const stats=data?.providers[source];const months=useMemo(()=>stats?.monthly.map(m=>({month:m.month,total:m.count}))||[],[stats]);
 const timeline=(month?:string)=>`${profileId?`/profiles/${profileId}?tab=timeline`:'/dashboard?view=photos'}&provider=${source}${month?`&month=${month}`:''}#timeline`;
 return <section className={`social-analytics ${source}`}><div className="feed-heading"><h2>{profileId?'Activity and interactions':'Social activity'}</h2><div className="provider-tabs" aria-label="Source platform">{Object.entries(labels).map(([key,label])=><button aria-pressed={source===key} className={source===key?'selected':''} key={key} onClick={()=>setSource(key)}>{label}</button>)}</div></div>
 {error?<div role="alert"><p>Statistics are unavailable right now.</p><button className="button button-soft" onClick={()=>setAttempt(n=>n+1)}>Retry</button></div>:!stats?<p role="status">Loading statistics…</p>:<>
 <div className="analytics-totals">{[[profileId?'Posts':'People',profileId?stats.posts:stats.people],[profileId?'Authors':'People who posted',stats.authors],['Imported posts',stats.posts],['Likes received',stats.likes],['Comments received',stats.comments],['With local media',stats.local_photo_posts]].map(([label,value],i)=><Link href={timeline()} key={i}><b>{n(Number(value))}</b><span>{String(label)}</span></Link>)}</div>
 <p className="analytics-scope">Posts from {stats.first?.slice(0,10)||'unknown'} to {stats.latest?.slice(0,10)||'unknown'} · {stats.local_photo_posts}/{stats.posts} posts have local media</p>
 <div className="analytics-grid"><section className="analytics-months"><h3>Monthly posts</h3><MonthlyChart key={source} rows={months} label="Monthly posts" href={timeline}/></section>
 <Ranking title={profileId?'Post interactions':'Most interacted with'} rows={stats.leaders} caption="Likes and comments on imported posts"/>
 {stats.charts.filter(c=>c.rows.length).map(c=><Ranking key={c.title} title={c.title} rows={c.rows} caption={c.filter?`Distinct people · ${c.denominator} LinkedIn profiles`:c.title.toLowerCase().includes('active')?`${c.denominator} archived chats · open a person`:'Profile counts at collection time'} filter={c.filter}/>)}
 {source==='wechat'&&stats.chat&&<><Ranking title="Direct messages" rows={stats.chat.leaders} caption="Chat archive summary · open a conversation" messages/><Ranking title="Group chat" rows={stats.chat.group_leaders} caption="Chat archive summary · open a person"/><div className="chat-numbers"><span><b>{n(stats.chat.contacts)}</b> with DMs</span><span><b>{n(stats.chat.messages)}</b> archived DMs</span>{!profileId&&<><Link href="/profiles?type=group"><b>{n(stats.groups)}</b> groups</Link><Link href="/messages"><b>{n(stats.conversations)}</b> conversations</Link><Link href="/messages"><b>{n(stats.indexed_messages)}</b> searchable messages</Link></>}</div></>}
 </div></>}
 </section>;
}
function Ranking({title,rows,caption,filter,messages}:{title:string;rows:Row[];caption:string;filter?:string;messages?:boolean}){
 const max=Math.max(1,...rows.map(r=>r.value??r.count??0));
 return <section className="analytics-ranking"><h3>{title}</h3><p>{caption}</p>{rows.length?rows.map((r,i)=><Link key={`${r.profile_id}-${i}`} href={filter?`/profiles?${filter}=${encodeURIComponent(r.name)}`:`/profiles/${r.profile_id}${messages?'?tab=messages':''}`}><span>{r.name}</span><b>{n(r.value??r.count)}</b><i style={{width:`${(r.value??r.count??0)/max*100}%`}}/></Link>):<p className="muted">No records to rank for this source yet</p>}</section>;
}
