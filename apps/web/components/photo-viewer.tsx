"use client";
import {useEffect,useRef,useState} from 'react';
import {X,ZoomIn,ZoomOut,ExternalLink} from 'lucide-react';
export function PhotoViewer({src,alt,onClose}:{src:string;alt:string;onClose:()=>void}){
 const dialog=useRef<HTMLDialogElement>(null);const [zoom,setZoom]=useState(false);
 useEffect(()=>{dialog.current?.showModal();},[]);
 return <dialog ref={dialog} className="original-photo-dialog" onClose={onClose} onClick={e=>{if(e.target===e.currentTarget)dialog.current?.close();}} aria-label={alt}>
 <header><strong>{alt}</strong><button onClick={()=>setZoom(v=>!v)} aria-label={zoom?'适合窗口':'原尺寸放大'}>{zoom?<ZoomOut/>:<ZoomIn/>}</button><a href={src} target="_blank" rel="noreferrer" aria-label="打开原图"><ExternalLink/></a><button onClick={()=>dialog.current?.close()} aria-label="关闭原图"><X/></button></header>
 <div className={`original-photo-stage ${zoom?'zoomed':''}`}><img src={src} alt={alt} onClick={()=>setZoom(v=>!v)}/></div>
 </dialog>;
}
