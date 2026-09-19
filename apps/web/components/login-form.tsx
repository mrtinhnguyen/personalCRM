"use client";

import { FormEvent, useState } from "react";
import { ArrowRight, LockKeyhole, ShieldCheck } from "lucide-react";
import { useRouter } from "next/navigation";

export function LoginForm() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [totpCode, setTotpCode] = useState("");
  const [recoveryCode, setRecoveryCode] = useState("");
  const [needsTotp, setNeedsTotp] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true); setError("");
    await fetch("/api/v1/auth/csrf");
    const response = await fetch("/api/v1/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, password, totp_code: totpCode || null, recovery_code: recoveryCode || null }) });
    if (response.ok) { router.replace("/dashboard"); return; }
    const body = await response.json().catch(() => ({}));
    if (response.status === 401 && body.detail === "TOTP code required") setNeedsTotp(true);
    setError(body.detail ?? "登录失败，请检查账号或密码。");
    setBusy(false);
  }

  return <form className="login-form" onSubmit={submit}><div className="login-heading"><span className="login-icon"><LockKeyhole size={20} /></span><h1>欢迎回来</h1><p>你的数据保留在自己的 NAS 上。</p></div><label>邮箱<input type="email" name="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" required /></label><label>密码<input type="password" name="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="至少 12 个字符" required /></label>{needsTotp && <label>验证器代码<input inputMode="numeric" pattern="[0-9]{6}" autoComplete="one-time-code" value={totpCode} onChange={(e) => setTotpCode(e.target.value)} placeholder="000000" /></label>}{needsTotp && <label>或使用恢复码<input value={recoveryCode} onChange={e=>setRecoveryCode(e.target.value)} autoComplete="off" placeholder="一次性恢复码…" /></label>}{error && <p className="form-error">{error}</p>}<button className="button button-primary login-button" disabled={busy}>{busy ? "验证中…" : "登录"}<ArrowRight size={16} /></button><div className="login-note"><ShieldCheck size={15} /><span>支持 TOTP；登录会话和设备可以在设置中撤销。</span></div></form>;
}
