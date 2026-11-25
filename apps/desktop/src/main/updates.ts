import { app } from 'electron'
import {
  errorUpdateState,
  idleUpdateState,
  releaseToUpdate,
  UPDATE_API_URL,
  type UpdateState
} from '../shared/updates'

const CACHE_TTL_MS = 10 * 60 * 1000
const REQUEST_TIMEOUT_MS = 8000

let cached: UpdateState | null = null
let cachedAt = 0
let pending: Promise<UpdateState> | null = null

function endpoint(): string {
  const override = (process.env.CLIPWRIGHT_UPDATE_API || '').trim()
  if (!override) return UPDATE_API_URL
  try {
    const url = new URL(override)
    const loopback = ['127.0.0.1', 'localhost', '::1'].includes(url.hostname)
    if (url.protocol !== 'https:' && !(url.protocol === 'http:' && loopback)) return UPDATE_API_URL
    return url.toString()
  } catch {
    return UPDATE_API_URL
  }
}

function friendlyError(error: unknown, response?: Response): UpdateState {
  const current = app.getVersion()
  if (error instanceof Error && (error.name === 'AbortError' || error.name === 'TimeoutError')) {
    return errorUpdateState(current, 'GitHub did not respond in time. Try again when you are online.')
  }
  if (response) {
    if (response.status === 404) {
      return errorUpdateState(current, 'No published release was found for this app yet.')
    }
    if (response.status === 403 && response.headers.get('x-ratelimit-remaining') === '0') {
      return errorUpdateState(current, 'GitHub is rate-limiting update checks. Try again in a little while.')
    }
    if (response.status >= 500) {
      return errorUpdateState(current, 'GitHub is unavailable right now. Try again shortly.')
    }
    return errorUpdateState(current, `GitHub refused the update check (HTTP ${response.status}).`)
  }
  return errorUpdateState(current, 'The update check could not reach GitHub. Check your connection.')
}

export function cachedUpdate(currentVersion = app.getVersion()): UpdateState {
  if (cached && cached.currentVersion === currentVersion) return cached
  return idleUpdateState(currentVersion)
}

export async function checkForUpdates(currentVersion = app.getVersion(), force = false): Promise<UpdateState> {
  if (pending) return pending
  if (!force && cached && cached.currentVersion === currentVersion && Date.now() - cachedAt < CACHE_TTL_MS) {
    return cached
  }
  // Keep automated UI tests offline and fast unless they explicitly point at a stub.
  if (process.env.CLIPWRIGHT_E2E === '1' && !process.env.CLIPWRIGHT_UPDATE_API) {
    cached = idleUpdateState(currentVersion)
    cachedAt = Date.now()
    return cached
  }

  pending = (async () => {
    let response: Response | undefined
    try {
      response = await fetch(endpoint(), {
        method: 'GET',
        cache: 'no-store',
        redirect: 'error',
        signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
        headers: {
          Accept: 'application/vnd.github+json',
          'X-GitHub-Api-Version': '2022-11-28',
          'User-Agent': `Clipwright/${currentVersion} (+https://github.com/porkfrnd/clipwright)`
        }
      })
      if (!response.ok) {
        const state = friendlyError(undefined, response)
        cached = state
        cachedAt = Date.now()
        return state
      }
      const payload = (await response.json()) as unknown
      const state = releaseToUpdate(payload, currentVersion)
      cached = state
      cachedAt = Date.now()
      return state
    } catch (error) {
      const state = friendlyError(error, response)
      cached = state
      cachedAt = Date.now()
      return state
    } finally {
      pending = null
    }
  })()
  return pending
}
