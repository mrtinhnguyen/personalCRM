"use client";
import {useEffect,useRef,useState} from "react";
import type {Map as LeafletMap,LayerGroup} from "leaflet";
import "leaflet/dist/leaflet.css";
export type PlacePoint={label:string;latitude:number;longitude:number;count:number;first_seen?:string|null;last_seen?:string|null;sources?:string[];source_kind?:string;events?:{at:string;text:string;url?:string;source:string}[]};
const labels:Record<string,string>={wechat:"WeChat",instagram:"Instagram",linkedin:"LinkedIn",manual:"Manual"};
export function PlacesMap({points}:{points:PlacePoint[]}){
 const container=useRef<HTMLDivElement>(null),map=useRef<LeafletMap|null>(null),layer=useRef<LayerGroup|null>(null);
 const requestedView=useRef<'places'|'world'|PlacePoint>('places');
 const [ready,setReady]=useState(false),[year,setYear]=useState(""),[source,setSource]=useState(""),[selected,setSelected]=useState<PlacePoint|null>(null),[offline,setOffline]=useState(false);
 const years=[...new Set(points.flatMap(p=>(p.events||[]).map(e=>e.at?.slice(0,4))).filter(Boolean))].sort().reverse();
 const visible=points.filter(p=>(!source||p.sources?.includes(source))&&(!year||p.events?.some(e=>e.at?.startsWith(year))));
 useEffect(()=>{let cancelled=false;let observer:ResizeObserver;import('leaflet').then(async L=>{if(cancelled||!container.current)return;
 const instance=L.map(container.current,{minZoom:0,maxZoom:19,scrollWheelZoom:false,worldCopyJump:true}).setView([20,0],1);map.current=instance;
 // Local world polygons stay visible if the external detail tiles are offline.
 const land=await fetch('/vendor/world.geojson').then(r=>r.json()).catch(()=>null);
 if(cancelled)return;instance.createPane('worldFallback').style.zIndex='150';if(land)L.geoJSON(land,{pane:'worldFallback',style:{color:'#9cbbb0',weight:.6,fillColor:'#e3edda',fillOpacity:1},interactive:false}).addTo(instance);
 const tiles=L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',keepBuffer:2}).addTo(instance);
 tiles.on('tileerror',()=>setOffline(true));tiles.on('tileload',()=>setOffline(false));
 layer.current=L.layerGroup().addTo(instance);observer=new ResizeObserver(()=>instance.invalidateSize());observer.observe(container.current);setReady(true);
 });return()=>{cancelled=true;observer?.disconnect();map.current?.remove();map.current=null;setReady(false);};},[]);
 useEffect(()=>{if(!ready||!map.current||!layer.current)return;let cancelled=false;import('leaflet').then(L=>{if(cancelled||!layer.current||!map.current)return;layer.current.clearLayers();visible.forEach(p=>{
 const color=p.sources?.includes('instagram')?'#8e527b':p.sources?.includes('linkedin')?'#2465a9':'#147d73';
 const marker=L.circleMarker([p.latitude,p.longitude],{radius:Math.min(15,6+Math.sqrt(p.count)),weight:2,color:'#fff',fillColor:color,fillOpacity:.9,bubblingMouseEvents:false});
 const caption=document.createElement('span');caption.textContent=p.label;marker.bindTooltip(caption);marker.on('click',()=>setSelected(p));marker.addTo(layer.current!);
 });if(requestedView.current==='world')map.current.setView([20,0],0,{animate:false});
 else if(typeof requestedView.current==='object')map.current.setView([requestedView.current.latitude,requestedView.current.longitude],10,{animate:false});
 else if(visible.length)map.current.fitBounds(L.latLngBounds(visible.map(p=>[p.latitude,p.longitude])),{padding:[42,42],maxZoom:visible.length===1?10:12,animate:false});
 });return()=>{cancelled=true;};},[ready,points,year,source]);
 return <section className="places-map"><div className="map-filters"><label>Year<select value={year} onChange={e=>{requestedView.current="places";setYear(e.target.value);}}><option value="">All</option>{years.map(y=><option key={y}>{y}</option>)}</select></label><label>Source<select value={source} onChange={e=>{requestedView.current="places";setSource(e.target.value);}}><option value="">All sources</option>{[...new Set(points.flatMap(p=>p.sources||[]))].map(s=><option value={s} key={s}>{labels[s]||s}</option>)}</select></label><button className="button button-soft" onClick={()=>{requestedView.current="world";map.current?.setView([20,0],0);}}>Show the world</button><button className="button button-soft" onClick={()=>{requestedView.current="places";if(!map.current||!visible.length)return;import('leaflet').then(L=>map.current?.fitBounds(L.latLngBounds(visible.map(p=>[p.latitude,p.longitude])),{padding:[42,42],maxZoom:10}));}}>Fit all places</button></div>
 <div className="atlas-map" ref={container} role="region" aria-label="Social places map. Zoom out to the world with the buttons."/>
 {offline&&<p className="map-hint">Detail tiles are offline. Showing the local world outline.</p>}
 <div className="place-buttons">{visible.slice(0,12).map((p,i)=><button key={i} className={selected===p?'selected':''} onClick={()=>{requestedView.current=p;setSelected(p);map.current?.setView([p.latitude,p.longitude],10);}}>{p.label}<small>{p.count?`${p.count} visits`:'Profile address'}</small></button>)}</div>
 {selected&&<div className="place-detail" aria-live="polite"><strong>{selected.label}</strong><span>{selected.latitude.toFixed(5)}, {selected.longitude.toFixed(5)}</span><a href={`https://www.openstreetmap.org/?mlat=${selected.latitude}&mlon=${selected.longitude}#map=14/${selected.latitude}/${selected.longitude}`} target="_blank" rel="noreferrer">Open in OpenStreetMap</a>{(selected.events||[]).filter(e=>(!year||e.at.startsWith(year))&&(!source||e.source===source)).slice(0,12).map((e,i)=>e.url?<a key={i} href={e.url}>{e.at.slice(0,10)} · {e.text||'Open post'}</a>:<span key={i}>{e.at.slice(0,10)} · {e.text||'Imported place'}</span>)}</div>}
 </section>;
}
