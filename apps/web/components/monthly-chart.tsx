"use client";
import Link from "next/link";
import {useEffect,useMemo,useRef} from "react";
type Month={month:string;total:number;sent?:number;received?:number};
export function MonthlyChart({rows,label,href,stacked=false}:{rows:Month[];label:string;href:(month:string)=>string;stacked?:boolean}){
 const scroll=useRef<HTMLDivElement>(null);
 const months=useMemo(()=>{
  if(!rows.length)return [];
  const byMonth=new Map(rows.map(row=>[row.month,row]));
  const first=rows.reduce((a,b)=>a.month<b.month?a:b).month;
  const last=[new Date().toISOString().slice(0,7),...rows.map(row=>row.month)].sort().at(-1)!;
  const result:Month[]=[];const cursor=new Date(`${first}-01T00:00:00Z`);
  while(Number.isFinite(cursor.getTime())&&cursor.toISOString().slice(0,7)<=last){
   const month=cursor.toISOString().slice(0,7);result.push(byMonth.get(month)||{month,total:0,sent:0,received:0});cursor.setUTCMonth(cursor.getUTCMonth()+1);
  }
  return result;
 },[rows]);
 const max=Math.max(1,...months.map(row=>row.total));
 useEffect(()=>{if(scroll.current)scroll.current.scrollLeft=scroll.current.scrollWidth},[months.length]);
 const move=(direction:number)=>scroll.current?.scrollBy({left:direction*scroll.current.clientWidth*.8,behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});
 if(!months.length)return <p className="muted">尚无带日期的记录</p>;
 return <div className="monthly-chart"><div className="month-navigation"><span>{months[0].month} — {months.at(-1)!.month}{stacked&&<> · <em className="sent-key">我发送</em> / <em className="received-key">对方发送</em></>}</span><div><button aria-label={`${label}：查看更早月份`} onClick={()=>move(-1)}>←</button><button aria-label={`${label}：查看更近月份`} onClick={()=>move(1)}>→</button></div></div>
 <div className="month-bars" ref={scroll} role="region" aria-label={`${label}，按连续月份排列，可横向滑动`} tabIndex={0}>{months.map(row=>{
  const height=row.total/max*88;
  return <Link href={href(row.month)} key={row.month} data-month={row.month} data-total={row.total} aria-label={`${row.month}，${row.total} 条${stacked?`，我发送 ${row.sent||0}，对方发送 ${row.received||0}`:''}`} title={`${row.month} · ${row.total.toLocaleString()} 条`}><span className="month-column"><b>{row.total.toLocaleString('zh-CN')}</b><i style={{height}}>{stacked&&<><span className="received-bar" style={{flex:row.received||0}}/><span className="sent-bar" style={{flex:row.sent||0}}/></>}</i></span><small>{row.month.slice(2)}</small></Link>;
 })}</div><p className="month-caption">左右滑动查看全部月份 · 空月份为 0 · 点击查看该月记录</p></div>;
}
