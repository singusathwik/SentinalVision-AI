'use client';
import { useCallback, useEffect, useState } from 'react';
const API = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8010/api/v1';
type Person = {id:string;email:string;role:string;enabled:boolean};
type Preferences = {retention_days:number;confidence:number;sample_every:number};
type Rule = {id:string;name:string;threshold:number;persistence:number;cooldown:number;exit_grace:number;exit_margin:number};
type Model = {id:string;name:string;sha256:string;scope:string};

export function Controls({token, page}: {token:string;page:string}) {
  const [people,setPeople]=useState<Person[]>([]);
  const [rules,setRules]=useState<Rule[]>([]);
  const [models,setModels]=useState<Model[]>([]);
  const [prefs,setPrefs]=useState<Preferences|null>(null);
  const [message,setMessage]=useState('');
  const [busy,setBusy]=useState(false);
  const [offset,setOffset]=useState(0);
  const [selected,setSelected]=useState('');
  const call=useCallback(async (path:string, method='GET', body?:unknown) => {
    const r=await fetch(API+path,{method,headers:{Authorization:`Bearer ${token}`,'Content-Type':'application/json'},...(body ? {body:JSON.stringify(body)}:{})});
    const result=await r.json();
    if(!r.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Request validation failed');
    return result;
  },[token]);
  const refresh=useCallback(async()=>{
    if(page==='Settings') {setPrefs(await call('/preferences'));setPeople(await call(`/users?offset=${offset}&limit=20`));setRules(await call(`/rules?offset=${offset}&limit=20`));}
    if(page==='Model laboratory') setModels(await call(`/registry?offset=${offset}&limit=20`));
  },[call,offset,page]);
  useEffect(()=>{const t=setTimeout(()=>{void refresh().catch(e=>setMessage(String(e)));},0);return()=>clearTimeout(t);},[refresh]);
  async function run(fn:()=>Promise<void>, reload=true){setBusy(true);setMessage('');try{await fn();if(reload){await refresh();setMessage('Saved.');}}catch(e){setMessage(String(e));}finally{setBusy(false);}}
  if(!['Settings','Model laboratory'].includes(page))return null;
  return <section className="panel stack" style={{marginTop:20}}><h2>{page==='Settings'?'Workspace administration':'Model versions and promotion'}</h2>{message&&<p role="status">{message}</p>}
    {page==='Settings'&&prefs&&<>
      <form className="row" onSubmit={e=>{e.preventDefault();const d=new FormData(e.currentTarget);void run(async()=>{setPrefs(await call('/preferences','PUT',{retention_days:Number(d.get('retention')),confidence:Number(d.get('confidence')),sample_every:Number(d.get('sampling'))}));});}}>
        <label>Retention days<input name="retention" type="number" min="1" max="365" defaultValue={prefs.retention_days} required/></label>
        <label>Default detector confidence<input name="confidence" type="number" min="0.05" max="0.95" step="0.05" defaultValue={prefs.confidence} required/></label>
        <label>Process every Nth frame<input name="sampling" type="number" min="1" max="30" defaultValue={prefs.sample_every} required/></label>
        <button disabled={busy}>Save workspace defaults</button>
      </form><p className="muted">Defaults apply to new jobs. Existing jobs retain their configuration. Retention applies on the next maintenance cycle.</p>
      <h3>Account lifecycle</h3>{people.map(p=><div className="account-row" key={p.id}><span>{p.role}<br/>{p.email} · {p.enabled?'enabled':'disabled'}</span><button disabled={busy} onClick={()=>run(async()=>{await call(`/users/${p.id}/access`,'PUT',{role:p.role,enabled:!p.enabled});})}>{p.enabled?'Disable':'Enable'} {p.email}</button></div>)}
      <form className="row" onSubmit={e=>{e.preventDefault();const form=e.currentTarget;const d=new FormData(form);void run(async()=>{await call(`/users/${d.get('user')}/reset-password`,'POST',{new_password:d.get('password')});form.reset();});}}><label>Reset account<select name="user" aria-label="Reset account" required>{people.map(p=><option key={p.id} value={p.id}>{p.email}</option>)}</select></label><label>New account password<input name="password" type="password" minLength={12} autoComplete="new-password" required/></label><button disabled={busy}>Reset password and revoke sessions</button></form>
      <form className="row" onSubmit={e=>{e.preventDefault();const d=new FormData(e.currentTarget);void run(async()=>{await call('/auth/change-password','POST',{current_password:d.get('current'),new_password:d.get('new')});setMessage('Password changed. Sign out and sign in again.');},false);}}><label>Current password<input name="current" type="password" autoComplete="current-password" required/></label><label>Your new password<input name="new" type="password" minLength={12} autoComplete="new-password" required/></label><button disabled={busy}>Change my password</button></form>
      <h3>Rule thresholds</h3><label>Rule to revise<select aria-label="Rule to revise" value={selected} onChange={e=>setSelected(e.target.value)}><option value="">Select rule</option>{rules.map(r=><option key={r.id} value={r.id}>{r.name}</option>)}</select></label>
      {rules.filter(r=>r.id===selected).map(r=><form key={r.id} className="row" onSubmit={e=>{e.preventDefault();const d=new FormData(e.currentTarget);void run(async()=>{await call('/rules/'+r.id,'PUT',{...r,threshold:Number(d.get('threshold')),persistence:Number(d.get('persistence')),exit_grace:Number(d.get('grace'))});});}}><label>Rule threshold<input name="threshold" type="number" min="0.01" step="0.01" defaultValue={r.threshold} required/></label><label>Persistence seconds<input name="persistence" type="number" min="0" step="0.1" defaultValue={r.persistence} required/></label><label>Exit grace seconds<input name="grace" type="number" min="0" max="30" step="0.1" defaultValue={r.exit_grace} required/></label><button disabled={busy}>Save new rule version</button></form>)}
    </>}
    {page==='Model laboratory'&&<><p className="muted">Provision trusted weights in data/models and import a held-out validation report through the API. Promotion requires matching artifact hashes and rejects smoke-only evidence.</p><form className="row" onSubmit={e=>{e.preventDefault();const d=new FormData(e.currentTarget);void run(async()=>{await call('/registry','POST',{name:d.get('name'),filename:d.get('filename'),report_id:d.get('report')});});}}><label>Model name<input name="name" required/></label><label>Provisioned artifact filename<input name="filename" required/></label><label>Validation report ID<input name="report" required/></label><button disabled={busy}>Register model candidate</button></form>{models.map(m=><form className="stack" key={m.id} onSubmit={e=>{e.preventDefault();const d=new FormData(e.currentTarget);void run(async()=>{await call(`/registry/${m.id}/promote`,'POST',{reason:d.get('reason')});});}}><strong>{m.name} · {m.scope}</strong><label>Promotion reason<input name="reason" minLength={5} required/></label><button disabled={busy}>Promote {m.name}</button></form>)}<button disabled={busy} onClick={()=>run(async()=>{await call('/registry/reset-baseline','POST',{});})}>Restore configured baseline</button></>}
    {(offset > 0 || (page==='Settings'?Math.max(people.length,rules.length):models.length)>=20) && <div className="pagination-row"><button disabled={offset===0} onClick={()=>setOffset(Math.max(0,offset-20))}>Previous administration page</button><span>Page {offset/20+1}</span><button disabled={(page==='Settings'?Math.max(people.length,rules.length):models.length)<20} onClick={()=>setOffset(offset+20)}>Next administration page</button></div>}
  </section>;
}
