export type SetupStatus = {
  version: string
  needs_onboarding: boolean
  has_firecrawl: boolean
  has_firecrawl_backup?: boolean
  has_openrouter: boolean
  firecrawl_masked: string
  firecrawl_backup_masked?: string
  openrouter_masked: string
  opencode_found: boolean
  opencode_path?: string
  has_resume: boolean
  keys_path: string
  firecrawl_keys_url?: string
  openrouter_keys_url?: string
  auto_update?: boolean
}

export type Board = { id: string; label: string; enabled: boolean }

export type Job = {
  id: number
  url: string
  title: string
  company: string
  location?: string
  score?: number
  verdict?: string
  status?: string
  has_cover_letter?: boolean
  source?: string
  work_arrangement?: string
}

export type UpdateInfo = {
  update_available: boolean
  current: string
  latest?: string
  installer_url?: string
  sha256?: string
  error?: string
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body.detail || JSON.stringify(body)
    } catch { /* ignore */ }
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return res.json()
}

export const api = {
  setupStatus: () => fetch('/api/setup/status').then(r => json<SetupStatus>(r)),
  saveKeys: (body: Record<string, string>) =>
    fetch('/api/setup/keys', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(r => json<SetupStatus>(r)),
  getResume: () => fetch('/api/setup/resume').then(r => json<{ content: string }>(r)),
  saveResume: (content: string) =>
    fetch('/api/setup/resume', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
    }).then(r => json<{ ok: boolean }>(r)),
  getSources: () => fetch('/api/setup/sources').then(r => json<{ boards: Board[] }>(r)),
  saveSources: (job_boards: string[]) =>
    fetch('/api/setup/sources', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job_boards }),
    }).then(r => json<unknown>(r)),
  completeSetup: () =>
    fetch('/api/setup/complete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    }).then(r => json<SetupStatus>(r)),
  jobs: () => fetch('/api/jobs').then(r => json<Job[]>(r)),
  setStatus: (url: string, status: string) =>
    fetch('/api/status', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, status }),
    }).then(r => json<{ ok: boolean }>(r)),
  deleteJob: (url: string) =>
    fetch('/api/delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    }).then(r => json<{ ok: boolean }>(r)),
  getCoverLetter: (url: string) =>
    fetch(`/api/cover-letter?url=${encodeURIComponent(url)}`).then(async r => {
      if (r.status === 404) return { content: '' }
      return json<{ content: string }>(r)
    }),
  generateCoverLetter: (url: string) =>
    fetch('/api/generate-cover-letter', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    }).then(r => json<{ content: string }>(r)),
  runStatus: () => fetch('/api/run-status').then(r => json<{ active: boolean; label?: string }>(r)),
  cancelRun: () => fetch('/api/run/cancel', { method: 'POST' }).then(r => json<{ cancelled: boolean; message?: string }>(r)),
  deps: () => fetch('/api/deps').then(r => json<{ opencode_found: boolean; opencode_path?: string; version: string }>(r)),
  updateCheck: () => fetch('/api/update/check').then(r => json<UpdateInfo>(r)),
  setAutoUpdate: (auto_update: boolean) =>
    fetch('/api/setup/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ auto_update }),
    }).then(r => json<SetupStatus>(r)),
}

export function confirmDestructive(message: string): boolean {
  return window.confirm(message)
}

export async function guardActiveRun(actionLabel: string): Promise<boolean> {
  try {
    const st = await api.runStatus()
    if (!st.active) return true
    return window.confirm(
      `A run is in progress${st.label ? ` (${st.label})` : ''}. ${actionLabel} anyway?`,
    )
  } catch {
    return true
  }
}
