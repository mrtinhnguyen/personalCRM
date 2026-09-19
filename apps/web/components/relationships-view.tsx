"use client";

import Link from "next/link";
import { ArrowLeft, Network, ShieldCheck } from "lucide-react";
import { useEffect, useRef } from "react";

/**
 * Monica's production graph is deliberately kept as a canvas implementation.
 * It handles thousands of nodes much more predictably than an SVG tree and
 * already contains the useful interaction model: communities, pan/zoom,
 * search, edge weighting, group edges and Profile navigation.
 */
export function RelationshipsView() {
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const root = rootRef.current;
    const focus = new URLSearchParams(window.location.search).get("focus");
    const panel = root?.querySelector<HTMLElement>("[data-relationship-graph]");
    if (focus && panel) panel.dataset.graphSource += `&focus=${encodeURIComponent(focus)}`;
    const loadScript = (src: string) => new Promise<void>((resolve, reject) => {
      const existing = document.querySelector(`script[data-mon-suite="${src}"]`);
      if (existing) {
        if (src.includes("d3.min") ? !!(window as Window & { d3?: unknown }).d3 : !!(window as Window & { initMonicaGraph?: unknown }).initMonicaGraph) resolve();
        else existing.addEventListener("load", () => resolve(), { once: true });
        return;
      }
      const script = document.createElement("script");
      script.src = src;
      script.async = false;
      script.dataset.monSuite = src;
      script.onload = () => resolve();
      script.onerror = () => reject(new Error(`Unable to load ${src}`));
      document.body.appendChild(script);
    });
    void Promise.all([loadScript("/vendor/d3.min.js"), loadScript("/vendor/relationship-graph.js")])
      .then(() => (window as Window & { initMonicaGraph?: () => void }).initMonicaGraph?.())
      .catch(() => {
        const status = document.querySelector("[data-graph-status]");
        if (status) status.textContent = "关系图脚本加载失败，请刷新页面重试。";
      });
    return () => { const panel = root?.querySelector("[data-relationship-graph]") as (HTMLElement & { _destroyGraph?: () => void }) | null; panel?._destroyGraph?.(); };
  }, []);

  return <div className="page-wrap relationships-page" ref={rootRef}>
    <div className="page-heading">
      <div>
        <p className="eyebrow">RELATIONSHIP GRAPH</p>
        <h1>朋友圈关系图</h1>
        <p className="muted">沿用熟悉的关系图交互，点击节点打开人物资料。朋友圈互动、共同群关系和群成员边可以按需打开。</p>
      </div>
      <Link className="button button-soft" href="/dashboard"><ArrowLeft size={15} />返回总览</Link>
    </div>
    <section className="graph-source-note">
      <Network size={18} />
      <div><strong>朋友圈互动与已确认关系</strong><p>保留社区布局、搜索、拖动、缩放、边权筛选和节点详情；每个节点按明确账号映射打开对应人物。</p></div>
      <span><ShieldCheck size={14} />按需加载</span>
    </section>
    <section
      className="monica-graph-panel"
      data-relationship-graph
      data-graph-source="/api/v1/relationships/graph?format=monica"
      data-contact-url-template="/profiles/__CONTACT_HASH__"
    >
      <header className="monica-graph-header">
        <div><p className="eyebrow">WECHAT MOMENTS</p><h2>朋友圈关系图</h2><p className="muted">用已缓存朋友圈中的点赞、评论、回复、共同受众与共同群关系绘制。先使用离线坐标，再由 D3 动态演算社群布局。</p></div>
        <button className="button button-primary" type="button" data-graph-load>加载关系图</button>
      </header>
      <div className="monica-graph-controls" data-graph-controls hidden>
        <form className="monica-graph-search" role="search" data-graph-search-form>
          <label htmlFor="relationship-node-search">查找节点</label>
          <input id="relationship-node-search" type="search" list="relationship-node-options" autoComplete="off" placeholder="姓名或微信昵称" data-graph-search />
          <datalist id="relationship-node-options" data-graph-search-options />
          <button className="button button-soft" type="submit">定位</button>
        </form>
        <label className="graph-range" htmlFor="relationship-edge-filter">最低边权 <input id="relationship-edge-filter" type="range" min="0" max="100" step="1" defaultValue="0" data-graph-filter /><output data-graph-filter-value>0</output></label>
        <button className="button button-soft" type="button" data-graph-motion aria-pressed="false">节点运动：关</button>
        <label className="graph-checkbox"><input type="checkbox" data-graph-groups />加入共同群关系</label>
        <button className="button button-soft" type="button" data-graph-zoom-in>放大</button><button className="button button-soft" type="button" data-graph-zoom-out>缩小</button><button className="button button-soft" type="button" data-graph-reset>适合全部节点</button>
      </div>
      <p className="monica-graph-status" role="status" aria-live="polite" data-graph-status>尚未加载。滚动到本区块后自动读取关系图。</p>
      <div className="monica-graph-canvas-wrap">
        <canvas className="monica-graph-canvas" data-graph-canvas tabIndex={0} role="img" aria-label="动态朋友圈关系图，可搜索节点并使用方向键平移" />
      </div>
      <aside className="monica-graph-details" data-graph-details aria-live="polite">加载后，将指针移到节点上查看互动明细。</aside>
      <p className="monica-graph-footnote" data-graph-footnote hidden />
    </section>
  </div>;
}
