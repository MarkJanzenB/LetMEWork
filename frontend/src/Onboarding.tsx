import { useEffect, useState } from 'react'
import { api, type Board, type SetupStatus } from './api'

const STEPS = ['Keys', 'Resume', 'Sites', 'Ready'] as const

type Props = {
  onDone: (status: SetupStatus) => void
}

export function Onboarding({ onDone }: Props) {
  const [step, setStep] = useState(0)
  const [status, setStatus] = useState<SetupStatus | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const [firecrawl, setFirecrawl] = useState('')
  const [backup, setBackup] = useState('')
  const [openrouter, setOpenrouter] = useState('')
  const [resume, setResume] = useState('')
  const [boards, setBoards] = useState<Board[]>([])

  useEffect(() => {
    api.setupStatus().then(setStatus).catch(e => setError(String(e.message || e)))
    api.getResume().then(r => setResume(r.content || '')).catch(() => {})
    api.getSources().then(r => setBoards(r.boards || [])).catch(() => {})
  }, [])

  async function next() {
    setError('')
    setBusy(true)
    try {
      if (step === 0) {
        const body: Record<string, string> = {}
        if (firecrawl.trim()) body.firecrawl_key = firecrawl.trim()
        if (backup.trim()) body.firecrawl_backup_key = backup.trim()
        if (openrouter.trim()) body.openrouter_key = openrouter.trim()
        const st = Object.keys(body).length ? await api.saveKeys(body) : await api.setupStatus()
        setStatus(st)
        if (!st.has_firecrawl) throw new Error('Firecrawl API key is required.')
        if (!st.opencode_found) throw new Error('OpenCode not found — install it, then continue.')
        setStep(1)
      } else if (step === 1) {
        if (!resume.trim()) throw new Error('Add your resume text (or paste after PDF extract).')
        await api.saveResume(resume)
        setStep(2)
      } else if (step === 2) {
        const selected = boards.filter(b => b.enabled).map(b => b.id)
        if (!selected.length) throw new Error('Select at least one job board.')
        await api.saveSources(selected)
        setStep(3)
      } else {
        const st = await api.completeSetup()
        onDone(st)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="panel">
      <h2>Welcome to Let Me Work</h2>
      <div className="wizard-steps">
        {STEPS.map((label, i) => (
          <span key={label} className={i === step ? 'on' : ''}>{i + 1} · {label}</span>
        ))}
      </div>

      {step === 0 && (
        <>
          <p className="hint">Keys stay on this PC only. Path: {status?.keys_path || '…'}</p>
          <label htmlFor="fc">Firecrawl API key (required)</label>
          <input id="fc" type="password" value={firecrawl} onChange={e => setFirecrawl(e.target.value)}
            placeholder={status?.has_firecrawl ? `${status.firecrawl_masked} (saved)` : 'fc-…'} />
          <label htmlFor="fcb">Backup Firecrawl key (optional)</label>
          <input id="fcb" type="password" value={backup} onChange={e => setBackup(e.target.value)}
            placeholder={status?.has_firecrawl_backup ? `${status.firecrawl_backup_masked} (saved)` : 'fc-… backup'} />
          <label htmlFor="or">OpenRouter API key (optional)</label>
          <input id="or" type="password" value={openrouter} onChange={e => setOpenrouter(e.target.value)}
            placeholder={status?.has_openrouter ? `${status.openrouter_masked} (saved)` : 'sk-or-…'} />
          <p className="hint">
            OpenCode: {status?.opencode_found ? `found (${status.opencode_path || 'PATH'})` : 'missing — install from opencode.ai'}
          </p>
        </>
      )}

      {step === 1 && (
        <>
          <label htmlFor="resume">Your resume (markdown)</label>
          <textarea id="resume" value={resume} onChange={e => setResume(e.target.value)}
            placeholder="Paste resume markdown…" />
          <p className="hint">PDF upload remains available in Settings after setup.</p>
        </>
      )}

      {step === 2 && (
        <>
          <p>Choose job boards to scrape (at least one).</p>
          <div className="checks">
            {boards.map(b => (
              <label key={b.id}>
                <input
                  type="checkbox"
                  checked={b.enabled}
                  onChange={() =>
                    setBoards(prev => prev.map(x => x.id === b.id ? { ...x, enabled: !x.enabled } : x))
                  }
                />
                <span>{b.label}</span>
              </label>
            ))}
          </div>
        </>
      )}

      {step === 3 && (
        <p>
          You’re set. Click Finish, then Run Agent to scrape and score jobs.
          Cover letters stay on-demand per job.
        </p>
      )}

      {error && <div className="banner banner-warn">{error}</div>}

      <div className="actions" style={{ marginTop: '1rem' }}>
        {step > 0 && (
          <button type="button" className="btn" disabled={busy} onClick={() => setStep(s => s - 1)}>Back</button>
        )}
        <button type="button" className="btn btn-primary" disabled={busy} onClick={next}>
          {step === 3 ? 'Finish' : 'Continue'}
        </button>
      </div>
    </div>
  )
}
