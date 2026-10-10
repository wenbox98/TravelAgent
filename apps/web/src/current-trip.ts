const KEY = 'ta-current-trip'

// Each open tab owns its selected trip. The shared value only seeds a new tab.
export function readCurrentTrip(): string | null {
  try { const current = sessionStorage.getItem(KEY); if (current) return current } catch {}
  try { return localStorage.getItem(KEY) } catch { return null }
}

export function rememberCurrentTrip(session: string): void {
  try { sessionStorage.setItem(KEY, session) } catch {}
  try { localStorage.setItem(KEY, session) } catch {}
}
