"use client";
import {useEffect,useState} from 'react';
import {apiFetch} from '../lib/api';
export function TotpSettings(){
 const [enabled,setEnabled]=useState(false),[secret,setSecret]=useState(''),[code,setCode]=useState(''),[recovery,setRecovery]=useState<string[]>([]),[error,setError]=useState('');
 useEffect(()=>{fetch('/api/v1/auth/totp/status').then(r=>r.json()).then(x=>setEnabled(x.enabled)).catch(()=>setError('无法读取验证器设置'))},[]);
 async function setup(){const r=await apiFetch('/api/v1/auth/totp/setup',{method:'POST'});const x=await r.json();if(r.ok)setSecret(x.secret);else setError(x.detail)}
 async function verify(){const r=await apiFetch('/api/v1/auth/totp/verify',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code})});const x=await r.json();if(r.ok){setEnabled(true);setSecret('');setRecovery(x.recovery_codes)}else setError('验证码无效，请重新输入。')}
 return <section className="panel profile-card"><h2>验证器登录</h2><p>{enabled?'已启用两步验证':'为登录增加一次性验证码。验证成功后才启用。'}</p>{!enabled&&!secret&&<button className="button button-soft" onClick={()=>void setup()}>设置验证器</button>}{secret&&<><p>在验证器中添加账号，填写此密钥：</p><code>{secret}</code><form onSubmit={e=>{e.preventDefault();void verify()}}><label>验证器代码<input value={code} onChange={e=>setCode(e.target.value)} inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" required/></label><button className="button button-primary">验证并启用</button></form></>}{recovery.length>0&&<div><h3>保存恢复码</h3><p>每个代码可用于登录一次，只在这里显示本次生成的代码。</p><ul>{recovery.map(value=><li key={value}><code>{value}</code></li>)}</ul><button className="button button-soft" onClick={()=>setRecovery([])}>已保存，隐藏代码</button></div>}{error&&<p role="alert">{error}</p>}</section>
}
