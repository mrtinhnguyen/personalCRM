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
        if (status) status.textContent = "Could not load the graph scripts. Refresh and try again.";
      });
    return () => { const panel = root?.querySelector("[data-relationship-graph]") as (HTMLElement & { _destroyGraph?: () => void }) | null; panel?._destroyGraph?.(); };
  }, []);

  return <div className="page-wrap relationships-page" ref={rootRef}>
    <div className="page-heading">
      <div>
        <p className="eyebrow">Relationship graph</p>
        <h1>People you keep in touch with</h1>
        <p className="muted">Pan, zoom, and search the graph. Click a node to open that person. Moments interactions, shared groups, and membership edges can be turned on when you need them.</p>
      </div>
      <Link className="button button-soft" href="/dashboard"><ArrowLeft size={15} />Back to overview</Link>
    </div>
    <section className="graph-source-note">
      <Network size={18} />
      <div><strong>Moments interactions and confirmed relationships</strong><p>Community layout, search, drag, zoom, edge-weight filters, and node details stay in one view. Each node opens the person it is mapped to.</p></div>
      <span><ShieldCheck size={14} />Loaded on demand</span>
    </section>
    <section
      className="monica-graph-panel"
      data-relationship-graph
      data-graph-source="/api/v1/relationships/graph?format=monica"
      data-contact-url-template="/profiles/__CONTACT_HASH__"
    >
      <header className="monica-graph-header">
        <div><p className="eyebrow">WeChat Moments</p><h2>Interaction graph</h2><p className="muted">Drawn from cached likes, comments, replies, shared audiences, and shared groups. Offline coordinates load first; D3 then lays out the communities.</p></div>
        <button className="button button-primary" type="button" data-graph-load>Load graph</button>
      </header>
      <div className="monica-graph-controls" data-graph-controls hidden>
        <form className="monica-graph-search" role="search" data-graph-search-form>
          <label htmlFor="relationship-node-search">Find a node</label>
          <input id="relationship-node-search" type="search" list="relationship-node-options" autoComplete="off" placeholder="Name or nickname" data-graph-search />
          <datalist id="relationship-node-options" data-graph-search-options />
          <button className="button button-soft" type="submit">Locate</button>
        </form>
        <label className="graph-range" htmlFor="relationship-edge-filter">Minimum edge weight <input id="relationship-edge-filter" type="range" min="0" max="100" step="1" defaultValue="0" data-graph-filter /><output data-graph-filter-value>0</output></label>
        <button className="button button-soft" type="button" data-graph-motion aria-pressed="false">Node motion: off</button>
        <label className="graph-checkbox"><input type="checkbox" data-graph-groups />Include shared groups</label>
        <button className="button button-soft" type="button" data-graph-zoom-in>Zoom in</button><button className="button button-soft" type="button" data-graph-zoom-out>Zoom out</button><button className="button button-soft" type="button" data-graph-reset>Fit all nodes</button>
      </div>
      <p className="monica-graph-status" role="status" aria-live="polite" data-graph-status>Not loaded yet. The graph reads itself when this section is in view.</p>
      <div className="monica-graph-canvas-wrap">
        <canvas className="monica-graph-canvas" data-graph-canvas tabIndex={0} role="img" aria-label="Interactive relationship graph. Search nodes or pan with the arrow keys." />
      </div>
      <aside className="monica-graph-details" data-graph-details aria-live="polite">After it loads, hover a node for interaction details.</aside>
      <p className="monica-graph-footnote" data-graph-footnote hidden />
    </section>
  </div>;
}
