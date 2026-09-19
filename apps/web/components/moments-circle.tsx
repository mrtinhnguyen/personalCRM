"use client";
import Link from 'next/link';
import {useEffect,useRef,useState} from 'react';
import {loadScript} from '../lib/scripts';
type Node={id:string;label:string;url:string;x:number;y:number;out:number[];in:number[];direct:number;weight:number;group:number;groupOnly:boolean;reciprocity:number;like:number;comment:number;reply:number;mention:number;last?:string};
type Graph={center:{id:string;label:string;url:string};neighbors:Node[];maximumDirect:number;maximumWeight:number};
export function MomentsCircle({profileId}:{profileId:string}){
 const root=useRef<HTMLElement>(null);const [graph,setGraph]=useState<Graph|null>(null),[error,setError]=useState(false);
 useEffect(()=>{const abort=new AbortController();setGraph(null);setError(false);fetch(`/api/v1/profiles/${profileId}/moments-circle`,{signal:abort.signal}).then(r=>{if(!r.ok)throw Error();return r.json();}).then(setGraph).catch(e=>{if(e.name!=='AbortError')setError(true);});return()=>abort.abort();},[profileId]);
 useEffect(()=>{if(!graph)return;let cancelled=false;const element=root.current as (HTMLElement&{_destroyGraph?:()=>void})|null;void loadScript('/vendor/d3.min.js').then(()=>loadScript('/vendor/moments-circle.js')).then(()=>{if(!cancelled)document.dispatchEvent(new CustomEvent('wechat:lazy-loaded',{detail:{root:element}}));});return()=>{cancelled=true;element?._destroyGraph?.();if(element){delete element.dataset.momentsD3Ready;element.querySelector("svg")?.replaceChildren();}};},[graph]);
 const direct=graph?.neighbors.filter(n=>!n.groupOnly)||[];
 return <section className="panel profile-card moments-circle" ref={root} data-moments-d3-graph={graph?'':undefined}>
 <div className="panel-heading"><div><h2>朋友圈互动</h2><p className="muted">{direct.length} 位互动对象 · 强关系靠近中心</p></div><Link className="panel-link" href={`/relationships?focus=${profileId}`}>展开关系网络</Link></div>
 {error?<p role="alert">互动图读取失败，请重新打开此页。</p>:!graph?<p role="status">正在读取朋友圈互动…</p>:<>
 <div className="circle-counts">{['点赞','评论','回复','提醒'].map((label,i)=><span key={label}><b>{direct.reduce((sum,n)=>sum+n.out[i]+n.in[i],0).toLocaleString('zh-CN')}</b>{label}</span>)}</div>
 <div className="circle-controls"><label><input type="checkbox" data-moments-group-toggle/>共同群</label><label>互动下限 <input type="range" min="0" max="100" defaultValue="0" data-moments-filter/><output data-moments-filter-value>0</output></label><button className="button button-soft" data-moments-zoom-in>放大</button><button className="button button-soft" data-moments-zoom-out>缩小</button><button className="button button-soft" data-moments-reset>重置</button><button className="button button-soft" data-moments-motion aria-pressed="true">暂停运动</button></div>
 <svg data-moments-graph-svg className="circle-canvas" role="img" aria-label="以当前人为中心的朋友圈互动图，节点可点击打开联系人"/>
 <p className="map-hint">绿：互惠 · 橙：本人较主动 · 紫：对方较主动 · 虚线：共同群（80 人以内）</p><p className="circle-details" data-moments-graph-details aria-live="polite"/>
 <script type="application/json" data-moments-graph-data dangerouslySetInnerHTML={{__html:JSON.stringify(graph).replace(/</g,'\\u003c')}}/>
 <details className="circle-roster"><summary>互动明细与联系人（<span data-moments-visible-count>{direct.length}</span>）</summary><div>{direct.map(n=><Link href={n.url} key={n.id}><strong>{n.label}</strong><span>赞 {n.like} · 评论 {n.comment} · 回复 {n.reply}</span></Link>)}</div></details>
 </>}
 </section>;
}
