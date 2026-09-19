"use client";
import { useEffect, useState } from "react";
import { TotpSettings } from "./totp-settings";
import { apiFetch } from "../lib/api";
type Device = { id: string; current: boolean; user_agent: string; revoked_at?: string; created_at: string };
export function DeviceSessions() {
  const [devices, setDevices] = useState<Device[]>([]);
  const [error, setError] = useState("");
  async function load() { const response = await fetch('/api/v1/auth/sessions'); if (response.ok) setDevices(await response.json()); }
  useEffect(() => { void load(); }, []);
  async function revoke(id: string) { const response = await apiFetch(`/api/v1/auth/sessions/${id}/revoke`, {method:'POST'}); if (response.ok) await load(); else setError('未能退出设备，请重试。'); }
  return <div className="page-wrap"><div className="page-heading"><h1>登录设备</h1></div>{error && <p role="alert">{error}</p>}<section className="panel profile-card">{devices.filter(d => !d.revoked_at).map(device => <div className="detail-row" key={device.id}><div><strong>{device.current ? '当前设备' : '其他设备'}</strong><p className="muted">{device.user_agent?.includes('Mobile') ? '移动浏览器' : '电脑浏览器'} · {new Date(device.created_at).toLocaleDateString('zh-CN')}</p></div>{!device.current && <button className="button button-soft" onClick={() => void revoke(device.id)}>退出此设备</button>}</div>)}</section><TotpSettings/></div>;
}
