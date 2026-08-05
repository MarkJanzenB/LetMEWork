/** Ask the backend to download Setup, verify sha256, launch installer, quit. */
export async function applyUpdate(_installerUrl?: string, _expectedSha256?: string): Promise<void> {
  const res = await fetch('/api/update/apply', { method: 'POST' })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body.detail || JSON.stringify(body)
    } catch { /* ignore */ }
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  window.alert(
    'Installer launching. Close this window if the app does not quit. SmartScreen may ask More info → Run anyway.',
  )
}
