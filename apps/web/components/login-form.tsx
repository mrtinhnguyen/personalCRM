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

  function formatDetail(detail: unknown): string {
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      const messages = detail
        .map((item) => (item && typeof item === "object" && "msg" in item ? String((item as { msg: unknown }).msg) : null))
        .filter(Boolean);
      if (messages.length) return messages.join(" ");
    }
    return "Sign-in failed. Check the email or password.";
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true); setError("");
    await fetch("/api/v1/auth/csrf", { credentials: "same-origin" });
    const response = await fetch("/api/v1/auth/login", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email: email.trim(),
        password,
        totp_code: totpCode.trim() || null,
        recovery_code: recoveryCode.trim() || null,
      }),
    });
    if (response.ok) { router.replace("/dashboard"); return; }
    const body = await response.json().catch(() => ({}));
    if (response.status === 401 && body.detail === "TOTP code required") setNeedsTotp(true);
    setError(formatDetail(body.detail));
    setBusy(false);
  }

  return <form className="login-form" onSubmit={submit}><div className="login-heading"><span className="login-icon"><LockKeyhole size={20} /></span><h1>Welcome back</h1><p>Your data stays on a server you control.</p></div><label>Email<input type="email" name="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" required /></label><label>Password<input type="password" name="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="At least 12 characters" required /></label>{needsTotp && <label>Authenticator code<input inputMode="numeric" pattern="[0-9]{6}" autoComplete="one-time-code" value={totpCode} onChange={(e) => setTotpCode(e.target.value)} placeholder="000000" /></label>}{needsTotp && <label>Or a recovery code<input value={recoveryCode} onChange={e=>setRecoveryCode(e.target.value)} autoComplete="off" placeholder="One-time recovery code…" /></label>}{error && <p className="form-error">{error}</p>}<button className="button button-primary login-button" disabled={busy}>{busy ? "Checking…" : "Sign in"}<ArrowRight size={16} /></button><div className="login-note"><ShieldCheck size={15} /><span>TOTP is supported. Sessions and devices can be revoked in Settings.</span></div></form>;
}
