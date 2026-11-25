import type { UpdateState } from '$shared/updates'

const DISMISS_KEY = 'clipwright.updates.dismissed'

function readDismissed(): string {
  try {
    return localStorage.getItem(DISMISS_KEY) || ''
  } catch {
    return ''
  }
}

export const updates = $state({
  data: null as UpdateState | null,
  checking: false,
  dismissedVersion: readDismissed()
})

let started = false
let unsubscribe: (() => void) | null = null
let startTimer: ReturnType<typeof setTimeout> | null = null

export function updateIsAvailable(): boolean {
  return updates.data?.status === 'available'
}

export function updateIsDismissed(): boolean {
  return Boolean(
    updates.data?.status === 'available' &&
      updates.data.latestVersion &&
      updates.dismissedVersion === updates.data.latestVersion
  )
}

export function dismissUpdate(): void {
  const version = updates.data?.latestVersion
  if (!version) return
  updates.dismissedVersion = version
  try {
    localStorage.setItem(DISMISS_KEY, version)
  } catch {
    // Private storage failures should never break the shell.
  }
}

export function applyUpdateState(state: UpdateState): void {
  updates.data = state
  updates.checking = state.status === 'checking'
}

export async function refreshUpdateState(): Promise<void> {
  try {
    const state = await window.clipwright.updateState()
    if (state.status !== 'idle') applyUpdateState(state)
  } catch {
    // Silent: the update page offers an explicit retry.
  }
}

export async function checkForUpdates(force = false): Promise<UpdateState | null> {
  if (updates.checking) return updates.data
  updates.checking = true
  try {
    const state = await window.clipwright.checkForUpdates(force)
    applyUpdateState(state)
    return state
  } catch {
    const fallback: UpdateState = {
      status: 'error',
      currentVersion: updates.data?.currentVersion || '',
      error: 'The update check could not run. Try again in a moment.'
    }
    applyUpdateState(fallback)
    return fallback
  } finally {
    updates.checking = false
  }
}

export function startUpdateChecks(): void {
  if (started) return
  started = true
  unsubscribe = window.clipwright.onUpdateStatus((state) => applyUpdateState(state))
  void refreshUpdateState()
  // Let the shell and project list settle before making a network request.
  startTimer = setTimeout(() => {
    if (!updates.data || updates.data.status === 'idle' || updates.data.status === 'error') void checkForUpdates(false)
  }, 1800)
}

export function stopUpdateChecks(): void {
  started = false
  if (startTimer) clearTimeout(startTimer)
  startTimer = null
  unsubscribe?.()
  unsubscribe = null
}
