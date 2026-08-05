import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, confirmDestructive, guardActiveRun, type Job, type SetupStatus, type UpdateInfo } from './api'
import { Onboarding } from './Onboarding'
import { applyUpdate } from './update'

const TAB_OF: Record<string, string> = {
  none: 'none', applied: 'applied', ignored: 'ignored',
  interviewed: 'applied', rejected: 'applied', hired: 'applied', closed: 'ignored',
}

export default function App() {
  const [status, setStatus] = useState<SetupStatus | null>(null)
  const [jobs, setJobs] = useState<Job[]>([])
  const [tab, setTab] = useState('none')
  const [q, setQ] = useState('')
  const [error, setError] = useState('')
  const [update, setUpdate] = useState<UpdateInfo | null>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [cl, setCl] = useState<{ url: string; text: string; generating: boolean } | null>(null)
  const [running, setRunning] = useState(false)

  const refresh = useCallback(async () => {
    const [st, list] = await Promise.all([api.setupStatus(), api.jobs()])
    setStatus(st)
    setJobs(list)
  }, [])

  useEffect(() => {
    refresh().catch(e => setError(String(e.message || e)))
    api.updateCheck().then(setUpdate).catch(() => {})
  }, [refresh])

  useEffect(() => {
    if (!status || !update?.update_available) return
    if (!status.auto_update) return
    applyUpdate().catch(e => setError(String(e.message || e)))
  }, [status, update])

  const visible = useMemo(() => {
    return jobs.filter(j => (TAB_OF[j.status || 'none'] || 'none') === tab)
      .filter(j => {
        if (!q.trim()) return true
        const s = q.toLowerCase()
        return `${j.title} ${j.company}`.toLowerCase().includes(s)
      })
  }, [jobs, tab, q])

  async function runAgent() {
    if (!(await guardActiveRun('Start Run Agent'))) return
    setRunning(true)
    setError('')
    const es = new EventSource('/api/run')
    es.onmessage = async ({ data }) => {
      const ev = JSON.parse(data)
      if (ev.step === 'busy') {
        es.close(); setRunning(false); setError('A run is already in progress.'); return
      }
      if (ev.step === 'error') {
        es.close(); setRunning(false); setError(ev.message || 'Pipeline error'); return
      }
      if (ev.step === 'complete') {
        es.close(); setRunning(false); await refresh(); return
      }
    }
    es.onerror = () => { es.close(); setRunning(false); setError('Connection lost during run.') }
  }

  async function cancelRun() {
    if (!confirmDestructive('Cancel the active run?')) return
    await api.cancelRun()
  }

  async function openCl(job: Job) {
    const { content } = await api.getCoverLetter(job.url)
    setCl({ url: job.url, text: content || 'No cover letter yet.', generating: false })
  }

  async function generateCl() {
    if (!cl) return
    setCl({ ...cl, generating: true, text: 'Generating…' })
    try {
      const { content } = await api.generateCoverLetter(cl.url)
      setCl({ url: cl.url, text: content, generating: false })
      await refresh()
    } catch (e) {
      setCl({ ...cl, generating: false, text: `Failed: ${e instanceof Error ? e.message : e}` })
    }
  }

  function requestCloseCl() {
    if (cl?.generating) {
      if (!confirmDestructive('Still generating. Close anyway? The card updates when finished.')) return
    }
    const shouldRefresh = !!cl && !cl.generating && cl.text && !cl.text.startsWith('No cover') && !cl.text.startsWith('Failed')
    setCl(null)
    if (shouldRefresh) refresh()
  }

  async function deleteJob(job: Job) {
    if (!confirmDestructive(`Soft-delete “${job.title}”? It won't reappear on scrape.`)) return
    await api.deleteJob(job.url)
    await refresh()
  }

  if (!status) {
    return <div className="app"><p>Loading…</p>{error && <div className="banner banner-warn">{error}</div>}</div>
  }

  if (status.needs_onboarding) {
    return (
      <div className="app">
        <header className="header">
          <div>
            <h1>Let Me Work</h1>
            <p>AI Job finder — first-run setup</p>
          </div>
        </header>
        <Onboarding onDone={st => { setStatus(st); refresh() }} />
      </div>
    )
  }

  return (
    <div className="app">
      <header className="header">
        <div>
          <h1>Let Me Work <span className="badge">{status.version}</span></h1>
          <p>AI Job finder that matches your resume</p>
        </div>
        <div className="actions">
          <button type="button" className="btn" onClick={() => setSettingsOpen(true)}>Settings</button>
          <button type="button" className="btn btn-primary" disabled={running} onClick={runAgent}>
            {running ? 'Running…' : 'Run Agent'}
          </button>
          {running && <button type="button" className="btn btn-danger" onClick={cancelRun}>Cancel run</button>}
        </div>
      </header>

      {update?.update_available && !status.auto_update && (
        <div className="banner banner-update">
          <span>Update {update.latest} available (you have {update.current}).</span>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => applyUpdate().catch(e => setError(String(e.message || e)))}
          >
            Update now
          </button>
        </div>
      )}

      {error && <div className="banner banner-warn">{error}</div>}

      <div className="tabs">
        {(['none', 'applied', 'ignored'] as const).map(t => (
          <button key={t} type="button" className={`btn tab ${tab === t ? 'active' : ''}`} onClick={() => setTab(t)}>
            {t === 'none' ? 'Not Started' : t === 'applied' ? 'In progress' : 'Ignored'}
          </button>
        ))}
      </div>

      <div className="filters">
        <input placeholder="Search jobs…" value={q} onChange={e => setQ(e.target.value)} />
      </div>

      {visible.map(job => (
        <article key={job.url} className="job-card">
          <div className="meta">
            <span className="badge">{job.score ?? '?'}</span>
            {job.verdict && <span className="badge">{job.verdict}</span>}
            {job.source && <span className="badge">{job.source}</span>}
          </div>
          <h3>{job.title}</h3>
          <p className="hint">{job.company}{job.location ? ` · ${job.location}` : ''}</p>
          <div className="job-actions">
            <a className="btn" href={job.url} target="_blank" rel="noreferrer">Open</a>
            <button type="button" className="btn" onClick={() => openCl(job)}>
              {job.has_cover_letter ? 'Cover Letter' : 'Generate CL'}
            </button>
            <button type="button" className="btn btn-danger" onClick={() => deleteJob(job)}>Delete</button>
            <select
              value={job.status || 'none'}
              onChange={async e => { await api.setStatus(job.url, e.target.value); await refresh() }}
            >
              {['none', 'applied', 'ignored', 'interviewed', 'rejected', 'hired', 'closed'].map(s => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </div>
        </article>
      ))}

      {!visible.length && <p className="hint">No jobs in this tab.</p>}

      {cl && (
        <div className="modal-backdrop" onClick={e => e.target === e.currentTarget && requestCloseCl()}>
          <div className="modal" role="dialog" aria-modal="true">
            <div className="actions" style={{ justifyContent: 'space-between' }}>
              <strong>Cover Letter</strong>
              <div className="actions">
                <button type="button" className="btn" disabled={cl.generating} onClick={generateCl}>
                  {cl.generating ? 'Generating…' : (cl.text && !cl.text.startsWith('No ') ? 'Regenerate' : 'Generate')}
                </button>
                <button type="button" className="btn" onClick={requestCloseCl}>Close</button>
              </div>
            </div>
            <pre>{cl.text}</pre>
          </div>
        </div>
      )}

      {settingsOpen && (
        <SettingsModal
          status={status}
          onClose={() => setSettingsOpen(false)}
          onSaved={async () => { setSettingsOpen(false); await refresh() }}
        />
      )}
    </div>
  )
}

function SettingsModal({
  status, onClose, onSaved,
}: {
  status: SetupStatus
  onClose: () => void
  onSaved: () => void
}) {
  const [firecrawl, setFirecrawl] = useState('')
  const [backup, setBackup] = useState('')
  const [openrouter, setOpenrouter] = useState('')
  const [resume, setResume] = useState('')
  const [boards, setBoards] = useState<{ id: string; label: string; enabled: boolean }[]>([])
  const [autoUpdate, setAutoUpdate] = useState(!!status.auto_update)
  const [deps, setDeps] = useState('')
  const [err, setErr] = useState('')

  useEffect(() => {
    api.getResume().then(r => setResume(r.content || ''))
    api.getSources().then(r => setBoards(r.boards || []))
    api.deps().then(d => setDeps(d.opencode_found ? `OpenCode: ${d.opencode_path || 'found'}` : 'OpenCode: missing'))
  }, [])

  async function save() {
    setErr('')
    try {
      const body: Record<string, string> = {}
      if (firecrawl.trim()) body.firecrawl_key = firecrawl.trim()
      if (backup.trim()) body.firecrawl_backup_key = backup.trim()
      if (openrouter.trim()) body.openrouter_key = openrouter.trim()
      if (Object.keys(body).length) await api.saveKeys(body)
      if (resume.trim()) await api.saveResume(resume)
      const selected = boards.filter(b => b.enabled).map(b => b.id)
      if (!selected.length) throw new Error('Select at least one board')
      await api.saveSources(selected)
      await api.setAutoUpdate(autoUpdate)
      onSaved()
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <div className="modal-backdrop" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <h2>Settings</h2>
        <p className="hint">{deps}</p>
        <label>Firecrawl key</label>
        <input type="password" value={firecrawl} onChange={e => setFirecrawl(e.target.value)}
          placeholder={status.firecrawl_masked ? `${status.firecrawl_masked} (saved)` : 'fc-…'} />
        <label>Backup Firecrawl key</label>
        <input type="password" value={backup} onChange={e => setBackup(e.target.value)}
          placeholder={status.firecrawl_backup_masked || 'optional'} />
        <label>OpenRouter key</label>
        <input type="password" value={openrouter} onChange={e => setOpenrouter(e.target.value)}
          placeholder={status.openrouter_masked || 'optional'} />
        <label>Resume</label>
        <textarea value={resume} onChange={e => setResume(e.target.value)} />
        <label>Job boards</label>
        <div className="checks">
          {boards.map(b => (
            <label key={b.id}>
              <input type="checkbox" checked={b.enabled}
                onChange={() => setBoards(prev => prev.map(x => x.id === b.id ? { ...x, enabled: !x.enabled } : x))} />
              {b.label}
            </label>
          ))}
        </div>
        <label>
          <input type="checkbox" checked={autoUpdate} onChange={e => setAutoUpdate(e.target.checked)} />
          {' '}Automatically download and install updates (opt-in)
        </label>
        <div className="actions" style={{ marginTop: '0.5rem' }}>
          <button
            type="button"
            className="btn"
            onClick={async () => {
              try {
                const info = await api.updateCheck()
                if (!info.update_available) {
                  window.alert(`Up to date (${info.current}).`)
                } else if (window.confirm(`Update ${info.latest} available. Download and install now?`)) {
                  await applyUpdate()
                }
              } catch (e) {
                setErr(e instanceof Error ? e.message : String(e))
              }
            }}
          >
            Check for updates
          </button>
        </div>
        {err && <div className="banner banner-warn">{err}</div>}
        <div className="actions" style={{ marginTop: '1rem' }}>
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button type="button" className="btn btn-primary" onClick={save}>Save</button>
        </div>
      </div>
    </div>
  )
}
