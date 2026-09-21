"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowUpRight, Users, BriefcaseBusiness, GraduationCap, Network } from "lucide-react";
import {LocationAtlas} from "./location-atlas";
import { SocialAnalytics } from "./social-analytics";
import { SocialFeed } from "./social-feed";
import { formatNumber } from "../lib/format";

type Overview = { people: number; groups: number; companies: { name: string; count: number }[]; schools: { name: string; count: number }[] };
export function Dashboard() {
  const [overview, setOverview] = useState<Overview | null>(null);
  useEffect(() => { fetch("/api/v1/metrics/people-overview").then(r => r.ok ? r.json() : null).then(setOverview).catch(() => undefined); }, []);
  return <div className="page-wrap home-page">
    <div className="page-heading"><div><h1>People and updates</h1><p className="muted">What the people you know have been up to.</p></div><Link className="button button-soft" href="/profiles"><Users size={16}/>People {overview?.people != null ? formatNumber(overview.people) : ""}</Link></div>
    <SocialAnalytics/>
    <LocationAtlas/>
    <div className="home-layout"><main><SocialFeed/></main><aside className="insight-column">
      <section className="network-invitation"><Network size={32}/><h2>Explore the graph</h2><p>Start from one person and see who they interact with, plus the groups they share.</p><Link href="/relationships">Open the graph <ArrowUpRight size={16}/></Link></section>
      <Distribution title="Where people work" icon={<BriefcaseBusiness size={17}/>} rows={overview?.companies || []} kind="company"/>
      <Distribution title="Schools" icon={<GraduationCap size={17}/>} rows={overview?.schools || []} kind="school"/>
      <Link className="group-overview" href="/profiles?type=group"><Users size={22}/><span><strong>{overview?.groups != null ? formatNumber(overview.groups) : "—"} groups</strong><small>Members and shared connections</small></span><ArrowUpRight size={16}/></Link>
    </aside></div>
  </div>;
}
function Distribution({ title, icon, rows, kind }: { title: string; icon: React.ReactNode; rows: { name: string; count: number }[]; kind: string }) {
  const maximum = Math.max(...rows.map(row => row.count),1);
  return <section className="distribution"><h2>{icon}{title}</h2><p>Distinct people counted from archived work and education</p>{rows.length ? rows.map(row => <Link className="distribution-row" href={`/profiles?${kind}=${encodeURIComponent(row.name)}`} key={row.name}><span><strong>{row.name}</strong><b>{row.count}</b></span><i style={{ width:`${row.count / maximum * 100}%` }}/></Link>) : <p className="sidebar-empty">No work or school records yet</p>}</section>;
}
