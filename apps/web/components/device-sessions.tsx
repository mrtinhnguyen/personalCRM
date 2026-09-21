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
  async function revoke(id: string) { const response = await apiFetch(`/api/v1/auth/sessions/${id}/revoke`, {method:'POST'}); if (response.ok) await load(); else setError('Could not sign that device out. Try again.'); }
  return <div className="page-wrap"><div className="page-heading"><h1>Signed-in devices</h1></div>{error && <p role="alert">{error}</p>}<section className="panel profile-card">{devices.filter(d => !d.revoked_at).map(device => <div className="detail-row" key={device.id}><div><strong>{device.current ? 'This device' : 'Other device'}</strong><p className="muted">{device.user_agent?.includes('Mobile') ? 'Mobile browser' : 'Desktop browser'} · {new Date(device.created_at).toLocaleDateString('en-US')}</p></div>{!device.current && <button className="button button-soft" onClick={() => void revoke(device.id)}>Sign out this device</button>}</div>)}</section><TotpSettings/></div>;
}
