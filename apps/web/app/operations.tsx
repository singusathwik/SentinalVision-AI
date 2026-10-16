'use client';
import Image from 'next/image';
import { Controls } from './controls';
import { useCallback, useEffect, useState } from 'react';

const API = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8010/api/v1';

export function SecureVideo({ token, path, title }: { token: string; path: string; title: string }) {
  const [url, setUrl] = useState('');
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    let objectUrl = '';
    fetch(API + path, { headers: { Authorization: `Bearer ${token}` }, signal: controller.signal })
      .then(async r => { if (!r.ok) throw new Error('Video is not available yet or access was denied.'); return r.blob(); })
      .then(blob => { objectUrl = URL.createObjectURL(blob); setUrl(objectUrl); })
      .catch(e => { if (!controller.signal.aborted) setError(String(e)); });
    return () => { controller.abort(); URL.revokeObjectURL(objectUrl); };
  }, [path, token]);
  return <section className="panel"><h2>{title}</h2>{error && <p role="alert">{error}</p>}{url ? <video aria-label={title} src={url} controls muted style={{ width: '100%' }} /> : <p>Loading video…</p>}<p className="muted">Silent visual evidence. Timestamps and machine detections require human interpretation.</p></section>;
}

type Worker = { id: string; state: string; age_seconds: number; healthy: boolean };
type Camera = { id: string; name: string; status: string; monitor?: {enabled:boolean} };
type Job = { id: string; video_name?: string; state: string; config: { camera_id?: string } };
type User = { id: string; email: string; role: string };
type System = {pending_cleanup:number;failed_jobs:number; workers: Worker[]; storage: string; queue: string; retention_days: number };
type Trends = { daily: { date: string; events: number }[]; cameras: { camera: string; events: number }[] };
type Experiment = { id: string; scope: string; metrics: Record<string, number> };

export function Operations({ token, page, ruleIds }: { token: string; page: string; ruleIds: string[] }) {
  const [offset, setOffset] = useState(0);
  const [system, setSystem] = useState<System | null>(null);
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [trends, setTrends] = useState<Trends | null>(null);
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState('');
  const [selectedJob, setSelectedJob] = useState('');
  const call = useCallback(async (path: string, body?: unknown, method?: string) => {
    const r = await fetch(API + (['/users','/cameras','/jobs','/experiments'].includes(path) && !body && !method ? path + '?offset=' + offset + '&limit=20' : path), { method: method || (body ? 'POST' : 'GET'), headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }, ...(body ? { body: JSON.stringify(body) } : {}) });
    const data = await r.json();
    if (!r.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Request validation failed');
    return data;
  }, [token, offset]);
  const refresh = useCallback(async () => {
    try {
      if (page === 'System health' || page === 'Settings') setSystem(await call('/system'));
      if (page === 'Live monitoring' || page === 'Settings') { setCameras(await call('/cameras')); setJobs(await call('/jobs')); }
      if (page === 'Settings') setUsers(await call('/users'));
      if (page === 'Analytics') setTrends(await call('/analytics/trends'));
      if (page === 'Model laboratory') setExperiments(await call('/experiments'));
    } catch (e) { setError(String(e)); }
  }, [call, page]);
  useEffect(() => { const start = setTimeout(refresh, 0); const timer = setInterval(refresh, 2500); return () => { clearTimeout(start); clearInterval(timer); }; }, [refresh]);
  useEffect(() => {
    if (!selectedJob) return;
    let alive = true; let old = '';
    const update = async () => { try { const r = await fetch(`${API}/jobs/${selectedJob}/preview`, { headers: { Authorization: `Bearer ${token}` } }); if (!r.ok) return; const b = await r.blob(); if (!alive) return; URL.revokeObjectURL(old); old = URL.createObjectURL(b); setPreview(old); } catch { /* poll again after transient network failure */ } };
    void update(); const timer = setInterval(update, 1500);
    return () => { alive = false; clearInterval(timer); URL.revokeObjectURL(old); };
  }, [selectedJob, token]);
  async function run(fn: () => Promise<void>) { setError(''); setBusy(true); try { await fn(); await refresh(); } catch (e) { setError(String(e)); } finally { setBusy(false); } }
  return <div className="stack" style={{ marginTop: 20 }}>{error && <p className="error" role="alert">{error}</p>}
    {page === 'System health' && <section className="panel"><h2>Worker heartbeats</h2>{system?.workers.length ? system.workers.map(w => <div className="data-row" key={w.id}><span><strong>{w.id}</strong><small>{w.state} / Updated {w.age_seconds}s ago</small></span><span className={w.healthy ? 'badge' : 'badge warn'}>{w.healthy ? 'healthy' : 'stale'}</span></div>) : <p>No recent worker heartbeat. Start a worker before submitting jobs.</p>}<p className="muted">Queue: {system?.queue} / Storage: {system?.storage} / Cleanup pending: {system?.pending_cleanup ?? 0}</p></section>}
    {page === 'Live monitoring' && <section className="panel stack"><h2>Authorized camera sources</h2><p className="muted">Monitoring schedules successive 30-second captures. Tracks reset between segments and capture gaps can occur. Source presentation timestamps preserve playback gaps, with receive-time fallback; camera clocks are not synchronized. Administrators must provision hostname and IP allowlists.</p>{cameras.map(c => <div className="camera-card" key={c.id}><strong>{c.name}</strong><span>{c.status}</span><button disabled={busy} onClick={() => run(async () => { await call('/cameras/' + c.id + '/monitor', {enabled:!c.monitor?.enabled,rule_ids:ruleIds,segment_seconds:30}, 'PUT'); })}>{c.monitor?.enabled ? 'Stop monitoring' : 'Start continuous monitoring'}</button><button disabled={busy} onClick={() => run(async () => { const j = await call('/jobs', { camera_id: c.id, rule_ids: ruleIds }); setSelectedJob(j.id); })}>Capture 30 seconds</button><button disabled={busy} onClick={() => run(async () => { await call('/cameras/' + c.id, undefined, 'DELETE'); })}>Remove camera</button></div>)}<form className="stack" onSubmit={e => { e.preventDefault(); const form = e.currentTarget; const d = new FormData(form); void run(async () => { await call('/cameras', { name: d.get('name'), url: d.get('url'), authorized: true }); form.reset(); }); }}><label>Camera name<input name="name" required /></label><label>RTSP source (stored encrypted)<input name="url" type="password" autoComplete="off" required /></label><label className="row"><input type="checkbox" required />I am authorized to connect this camera.</label><button className="primary" disabled={busy}>Register camera</button></form>{jobs.filter(j => j.config.camera_id).map(j => <div className="row" key={j.id}><span>{j.video_name || 'Camera recording'} · {j.state}</span><button onClick={() => setSelectedJob(j.id)}>Watch preview</button>{['queued', 'running'].includes(j.state) && <button onClick={() => run(async () => { await call(`/jobs/${j.id}/cancel`, {}); })}>Stop capture</button>}</div>)}{preview && <Image unoptimized src={preview} alt="Latest annotated camera frame" width={640} height={480} style={{ width: '100%', height: 'auto' }} />}</section>}
    {page === 'Settings' && <section className="panel stack"><h2>Workspace access</h2><p>Automatic retention: {system?.retention_days ?? '…'} days. Active jobs are excluded. Administrator access is required to provision accounts.</p><form className="row" onSubmit={e => { e.preventDefault(); const form = e.currentTarget; const d = new FormData(form); void run(async () => { await call('/users', { email: d.get('email'), password: d.get('password'), role: d.get('role') }); form.reset(); }); }}><label>New user email<input name="email" type="email" required /></label><label>Temporary password<input name="password" type="password" minLength={12} required /></label><label>Role<select name="role" aria-label="New user role"><option value="viewer">Viewer</option><option value="operator">Operator</option><option value="admin">Admin</option></select></label><button disabled={busy}>Create account</button></form></section>}
    {page === 'Analytics' && <div className="grid"><section className="panel"><h2>Daily observations (UTC)</h2>{trends?.daily.map(d => <div className="data-row" key={d.date}><span>{d.date}</span><strong>{d.events}</strong></div>)}</section><section className="panel"><h2>Per-source observations</h2>{trends?.cameras.map(c => <div className="data-row" key={c.camera}><span>{c.camera}</span><strong>{c.events}</strong></div>)}</section></div>}
    {page === 'Model laboratory' && <section className="panel"><h2>Recorded local experiments</h2><button disabled={busy} onClick={() => run(async () => { await call('/experiments/publish-local', {}); })}>Publish local training report</button>{experiments.length ? experiments.map(e => <div key={e.id}><p>{e.id} · {e.scope}</p><pre>{JSON.stringify(e.metrics, null, 2)}</pre></div>) : <p>No published experiment reports. Run training/evaluation and publish a report for this tenant.</p>}</section>}
    {['Live monitoring', 'Model laboratory'].includes(page) && (offset > 0 || Math.max(cameras.length,jobs.length,experiments.length) >= 20) && <div className="pagination-row"><button disabled={offset===0} onClick={()=>setOffset(Math.max(0,offset-20))}>Previous operations page</button><span>Page {offset/20+1}</span><button disabled={Math.max(users.length,cameras.length,jobs.length,experiments.length)<20} onClick={()=>setOffset(offset+20)}>Next operations page</button></div>}
    <Controls token={token} page={page}/>
  </div>;
}
