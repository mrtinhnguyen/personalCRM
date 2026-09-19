"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowUpRight, Users, BriefcaseBusiness, GraduationCap, Network } from "lucide-react";
import {LocationAtlas} from "./location-atlas";
import { SocialAnalytics } from "./social-analytics";
import { SocialFeed } from "./social-feed";

type Overview = { people: number; groups: number; companies: { name: string; count: number }[]; schools: { name: string; count: number }[] };
export function Dashboard() {
  const [overview, setOverview] = useState<Overview | null>(null);
  useEffect(() => { fetch("/api/v1/metrics/people-overview").then(r => r.ok ? r.json() : null).then(setOverview).catch(() => undefined); }, []);
  return <div className="page-wrap home-page">
    <div className="page-heading"><div><h1>人与近况</h1><p className="muted">看看朋友最近的生活。</p></div><Link className="button button-soft" href="/profiles"><Users size={16}/>联系人 {overview?.people.toLocaleString("zh-CN") ?? ""}</Link></div>
    <SocialAnalytics/>
    <LocationAtlas/>
    <div className="home-layout"><main><SocialFeed/></main><aside className="insight-column">
      <section className="network-invitation"><Network size={32}/><h2>探索关系</h2><p>从一个人出发，看看互动对象与共同群组。</p><Link href="/relationships">打开关系图 <ArrowUpRight size={16}/></Link></section>
      <Distribution title="朋友在哪里工作" icon={<BriefcaseBusiness size={17}/>} rows={overview?.companies || []} kind="company"/>
      <Distribution title="大家的学校" icon={<GraduationCap size={17}/>} rows={overview?.schools || []} kind="school"/>
      <Link className="group-overview" href="/profiles?type=group"><Users size={22}/><span><strong>{overview?.groups.toLocaleString("zh-CN") ?? "—"} 个群组</strong><small>成员与共同连接</small></span><ArrowUpRight size={16}/></Link>
    </aside></div>
  </div>;
}
function Distribution({ title, icon, rows, kind }: { title: string; icon: React.ReactNode; rows: { name: string; count: number }[]; kind: string }) {
  const maximum = Math.max(...rows.map(row => row.count),1);
  return <section className="distribution"><h2>{icon}{title}</h2><p>按已收录经历中的不同联系人计数</p>{rows.length ? rows.map(row => <Link className="distribution-row" href={`/profiles?${kind}=${encodeURIComponent(row.name)}`} key={row.name}><span><strong>{row.name}</strong><b>{row.count}</b></span><i style={{ width:`${row.count / maximum * 100}%` }}/></Link>) : <p className="sidebar-empty">尚无可统计的经历</p>}</section>;
}
