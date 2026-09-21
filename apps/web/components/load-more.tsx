"use client";
import {useEffect,useRef} from "react";

/** A visible paging boundary, with an ordinary button for retry and keyboards. */
export function LoadMore({cursor,busy,error,onLoad,label="Load more"}:{cursor:string;busy:boolean;error?:boolean;onLoad:()=>void;label?:string}){
 const boundary=useRef<HTMLDivElement>(null),action=useRef(onLoad);
 action.current=onLoad;
 useEffect(()=>{
  if(busy||error||!boundary.current)return;
  let requested=false;
  const observer=new IntersectionObserver(entries=>{
   if(!requested&&entries.some(entry=>entry.isIntersecting)){
    requested=true;observer.disconnect();action.current();
   }
  },{rootMargin:"0px 0px 160px 0px"});
  observer.observe(boundary.current);
  return()=>observer.disconnect();
 },[cursor,busy,error]);
 return <div className="load-more-boundary" ref={boundary}><button className="button button-soft feed-more" disabled={busy} onClick={onLoad}>{busy?"Loading…":error?"Retry":label}</button></div>;
}
