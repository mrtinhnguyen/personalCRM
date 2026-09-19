"use client";
import Link from 'next/link';
import {useEffect,useState,useMemo} from 'react';
import {MonthlyChart} from "./monthly-chart";
type Row={name:string;count?:number;value?:number;profile_id:string;posts?:number};
type Stats={people:number;authors:number;posts:number;likes:number;comments:number;local_photo_posts:number;first?:string;latest?:string;groups?:number;indexed_messages?:number;conversations?:number;monthly:{month:string;count:number}[];leaders:Row[];charts:{title:string;rows:Row[];denominator:number;filter?:string}[];chat?:{contacts:number;messages:number;sent:number;received:number;leaders:Row[];group_leaders:Row[]}};
const labels:Record<string,string>={wechat:'微信',instagram:'Instagram',linkedin:'LinkedIn'};
const n=(v:number|undefined)=>v==null?'—':v.toLocaleString('zh-CN');
export function SocialAnalytics({profileId}:{profileId?:string}){
 const [attempt,setAttempt]=useState(0);
 const [data,setData]=useState<{providers:Record<string,Stats>;as_of:string;scope:string}|null>(null),[source,setSource]=useState('wechat'),[error,setError]=useState(false);
 useEffect(()=>{const abort=new AbortController();setData(null);setError(false);fetch(`/api/v1/metrics/social${profileId?`?profile_id=${profileId}`:''}`,{signal:abort.signal}).then(r=>{if(!r.ok)throw Error();return r.json();}).then(setData).catch(e=>{if(e.name!=='AbortError')setError(true);});return()=>abort.abort();},[profileId,attempt]);
 const stats=data?.providers[source];const months=useMemo(()=>stats?.monthly.map(m=>({month:m.month,total:m.count}))||[],[stats]);
 const timeline=(month?:string)=>`${profileId?`/profiles/${profileId}?tab=timeline`:'/dashboard?view=photos'}&provider=${source}${month?`&month=${month}`:''}#timeline`;
 return <section className={`social-analytics ${source}`}><div className="feed-heading"><h2>{profileId?'社交与互动统计':'社交关系统计'}</h2><div className="provider-tabs" aria-label="统计平台">{Object.entries(labels).map(([key,label])=><button aria-pressed={source===key} className={source===key?'selected':''} key={key} onClick={()=>setSource(key)}>{label}</button>)}</div></div>
 {error?<div role="alert"><p>暂时无法读取统计。</p><button className="button button-soft" onClick={()=>setAttempt(n=>n+1)}>重试统计</button></div>:!stats?<p role="status">正在读取统计…</p>:<>
 <div className="analytics-totals">{[[profileId?'发布动态':'来源人物',profileId?stats.posts:stats.people],[profileId?'动态作者':'发布过动态',stats.authors],['已收录动态',stats.posts],['收到点赞',stats.likes],['收到评论',stats.comments],['有本地媒体',stats.local_photo_posts]].map(([label,value],i)=><Link href={timeline()} key={i}><b>{n(Number(value))}</b><span>{String(label)}</span></Link>)}</div>
 <p className="analytics-scope">动态范围 {stats.first?.slice(0,10)||'日期未收录'} 至 {stats.latest?.slice(0,10)||'日期未收录'} · {stats.local_photo_posts}/{stats.posts} 条动态有本地媒体</p>
 <div className="analytics-grid"><section className="analytics-months"><h3>每月动态</h3><MonthlyChart key={source} rows={months} label="每月动态" href={timeline}/></section>
 <Ranking title={profileId?'动态互动':'收到互动最多的人'} rows={stats.leaders} caption="已收录帖子的赞与评论总数"/>
 {stats.charts.filter(c=>c.rows.length).map(c=><Ranking key={c.title} title={c.title} rows={c.rows} caption={c.filter?`不同联系人 · ${c.denominator} 位 LinkedIn 人物`:c.title.includes('活跃')?`${c.denominator} 份私聊归档摘要 · 点击查看一位对应联系人`:'采集时的主页计数'} filter={c.filter}/>)}
 {source==='wechat'&&stats.chat&&<><Ranking title="私聊消息" rows={stats.chat.leaders} caption="Chatlog 归档摘要，点击打开聊天" messages/><Ranking title="群聊发言" rows={stats.chat.group_leaders} caption="Chatlog 归档摘要，点击打开联系人"/><div className="chat-numbers"><span><b>{n(stats.chat.contacts)}</b> 有私聊记录</span><span><b>{n(stats.chat.messages)}</b> 归档私聊消息</span>{!profileId&&<><Link href="/profiles?type=group"><b>{n(stats.groups)}</b> 群组</Link><Link href="/messages"><b>{n(stats.conversations)}</b> 会话</Link><Link href="/messages"><b>{n(stats.indexed_messages)}</b> 已进入搜索的消息</Link></>}</div></>}
 </div></>}
 </section>;
}
function Ranking({title,rows,caption,filter,messages}:{title:string;rows:Row[];caption:string;filter?:string;messages?:boolean}){
 const max=Math.max(1,...rows.map(r=>r.value??r.count??0));
 return <section className="analytics-ranking"><h3>{title}</h3><p>{caption}</p>{rows.length?rows.map((r,i)=><Link key={`${r.profile_id}-${i}`} href={filter?`/profiles?${filter}=${encodeURIComponent(r.name)}`:`/profiles/${r.profile_id}${messages?'?tab=messages':''}`}><span>{r.name}</span><b>{n(r.value??r.count)}</b><i style={{width:`${(r.value??r.count??0)/max*100}%`}}/></Link>):<p className="muted">当前来源尚无可统计的记录</p>}</section>;
}
