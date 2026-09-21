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
 <div className="panel-heading"><div><h2>Moments interactions</h2><p className="muted">{direct.length} people · stronger ties sit closer to the center</p></div><Link className="panel-link" href={`/relationships?focus=${profileId}`}>Open the full graph</Link></div>
 {error?<p role="alert">Could not load the interaction graph. Reopen this page.</p>:!graph?<p role="status">Loading Moments interactions…</p>:<>
 <div className="circle-counts">{['Likes','Comments','Replies','Mentions'].map((label,i)=><span key={label}><b>{direct.reduce((sum,n)=>sum+n.out[i]+n.in[i],0).toLocaleString('en-US')}</b>{label}</span>)}</div>
 <div className="circle-controls"><label><input type="checkbox" data-moments-group-toggle/>Shared groups</label><label>Minimum interactions <input type="range" min="0" max="100" defaultValue="0" data-moments-filter/><output data-moments-filter-value>0</output></label><button className="button button-soft" data-moments-zoom-in>Zoom in</button><button className="button button-soft" data-moments-zoom-out>Zoom out</button><button className="button button-soft" data-moments-reset>Reset</button><button className="button button-soft" data-moments-motion aria-pressed="true">Pause motion</button></div>
 <svg data-moments-graph-svg className="circle-canvas" role="img" aria-label="Moments interaction graph centered on this person. Click a node to open them."/>
 <p className="map-hint">Green: reciprocal · orange: you more active · purple: they more active · dashed: shared groups (up to 80 people)</p><p className="circle-details" data-moments-graph-details aria-live="polite"/>
 <script type="application/json" data-moments-graph-data dangerouslySetInnerHTML={{__html:JSON.stringify(graph).replace(/</g,'\\u003c')}}/>
 <details className="circle-roster"><summary>Interaction details（<span data-moments-visible-count>{direct.length}</span>）</summary><div>{direct.map(n=><Link href={n.url} key={n.id}><strong>{n.label}</strong><span>likes {n.like} · comments {n.comment} · replies {n.reply}</span></Link>)}</div></details>
 </>}
 </section>;
}
