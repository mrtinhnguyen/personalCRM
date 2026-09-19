"use client";

import Link from "next/link";
import { Activity, Database, GitBranch, LayoutDashboard, LogOut, MessageCircle, Search, Settings2, Users } from "lucide-react";
import { KeyboardEvent, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { useRouter } from "next/navigation";
import { apiFetch } from "../lib/api";

const navigation = [
  { id: "dashboard", label: "总览", href: "/dashboard", icon: LayoutDashboard },
  { id: "profiles", label: "联系人", href: "/profiles", icon: Users },
  { id: "timeline", label: "时间线", href: "/dashboard#timeline", icon: Activity },
  { id: "relationships", label: "关系网络", href: "/relationships", icon: GitBranch },
  { id: "messages", label: "聊天", href: "/messages", icon: MessageCircle },
  { id: "imports", label: "导入中心", href: "/imports", icon: Database }
];

export function AppShell({ active, children }: { active: string; children: ReactNode }) {
  const router = useRouter();
  const [query, setQuery] = useState("");
  useEffect(() => {
    fetch("/api/v1/me").then((response) => {
      if (response.status === 401) window.location.assign("/login");
    }).catch(() => undefined);
  }, []);
  function search(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter" && query.trim()) router.push(`/search?q=${encodeURIComponent(query.trim())}`);
  }
  async function logout() {
    await apiFetch("/api/v1/auth/logout", { method: "POST" });
    router.replace("/login");
  }
  return <div className="app-frame"><a className="skip-link" href="#main-content">跳转到主要内容</a>
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark">M</div><div><strong>Monica Next</strong><span>private relationship CRM</span></div></div>
      <nav className="nav-list" aria-label="主导航">
        {navigation.map((item) => { const Icon = item.icon; return <Link className={`nav-item ${active === item.id ? "active" : ""}`} href={item.href} key={item.id}><Icon size={17} strokeWidth={1.8} /><span>{item.label}</span></Link>; })}
      </nav>
      <div className="sidebar-bottom"><Link className="nav-item" href="/settings"><Settings2 size={17} /><span>设置</span></Link><button className="nav-item" onClick={() => void logout()}><LogOut size={17} /><span>退出</span></button></div>
    </aside>
    <main className="main-content" id="main-content">
      <header className="topbar"><div className="mobile-brand"><div className="brand-mark">M</div><strong>Monica Next</strong></div><label className="global-search"><Search size={17} /><input value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={search} placeholder="搜索联系人、标签或时间线" aria-label="全局搜索" /></label><Link className="sync-status" href="/imports">导入管理</Link></header>
      {process.env.NEXT_PUBLIC_DEMO_MODE === "1" && <div role="note" style={{position:"sticky",top:62,zIndex:40,padding:"10px 28px",background:"#e8f2ee",color:"#176653",fontSize:13,borderBottom:"1px solid #d2e6de"}}>演示数据 · 所有人物、关系与内容均为虚构 · SYNTHETIC DEMO</div>}
      {children}
    </main>
  </div>;
}
