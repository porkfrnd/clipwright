import { request as rawRequest, resolveAsset } from './api'
import type { Job, AppSettings, ProviderProfile, HardwareReport, EngineStatus } from '$shared/types'

export const appState = $state({
  booted: false,
  engineStatus: 'starting' as EngineStatus,
  engineDetail: '' as string,
  fatal: null as null | { reason: string; logTail: string[] },
  settings: null as AppSettings | null,
  providers: [] as ProviderProfile[],
  defaultProfileId: null as string | null,
  hardware: null as HardwareReport | null,
  appInfo: null as any,
  projectId: null as string | null,
  projects: [] as any[],
  route: 'home',
  toasts: [] as { id: number; kind: 'info' | 'error' | 'success'; message: string; details?: string }[],
  refreshKey: 0
})

let toastId = 1

export function toast(kind: 'info' | 'error' | 'success', message: string, details?: string) {
  const id = toastId++
  appState.toasts.push({ id, kind, message, details })
  setTimeout(() => {
    appState.toasts = appState.toasts.filter((t) => t.id !== id)
  }, kind === 'error' ? 9000 : 4500)
}

export async function refreshBoot() {
  const [info, settings, providers, hardware, projects] = await Promise.all([
    window.clipwright.appInfo(),
    rawRequest('settings.get').catch(() => null),
    rawRequest('provider.list').catch(() => null),
    rawRequest('hardware.detect').catch(() => null),
    rawRequest('project.list').catch(() => null)
  ])
  appState.appInfo = info
  if (settings?.settings) appState.settings = settings.settings as AppSettings
  if (providers) {
    appState.providers = providers.providers || []
    appState.defaultProfileId = providers.defaultProfileId || null
  }
  appState.hardware = hardware as HardwareReport
  if (projects) appState.projects = projects.projects || []
  appState.booted = true
  applyAppearance()
}

export function applyAppearance() {
  const s = appState.settings?.app
  if (!s) return
  const root = document.documentElement
  root.dataset.theme = s.theme || 'velvet'
  root.dataset.appearance = s.appearance || 'dark'
  root.dataset.density = s.density || 'comfortable'
  root.dataset.motion = s.reduceMotion ? 'reduced' : 'full'
  root.style.setProperty('color-scheme', s.appearance === 'light' || s.theme === 'ivory' ? 'light' : 'dark')
}

export async function saveSettings(key: string, value: Record<string, any>) {
  const result = await rawRequest('settings.set', { key, value })
  if (appState.settings) {
    appState.settings = { ...appState.settings, [key]: result.value }
  }
  return result
}

export function setRoute(route: string, projectId?: string) {
  if (projectId !== undefined) appState.projectId = projectId
  appState.route = route
  location.hash = projectId ? `#/${route}/${projectId}` : `#/${route}`
}

export function parseRoute() {
  const parts = location.hash.replace(/^#\/?/, '').split('/').filter(Boolean)
  const route = parts[0] || 'home'
  if (parts[1]) appState.projectId = parts[1]
  appState.route = route
}

export const jobState = $state({
  jobs: {} as Record<string, Job>,
  order: [] as string[]
})

export function ingestJobEvent(event: { method: string; params: any }) {
  const { method, params } = event
  if (method === 'job.state') {
    const existing = jobState.jobs[params.jobId]
    jobState.jobs[params.jobId] = {
      ...(existing || ({ id: params.jobId, params: {}, checkpoint: {}, createdAt: '', updatedAt: '' } as any)),
      ...params,
      state: params.state
    } as Job
    if (!jobState.order.includes(params.jobId)) jobState.order.unshift(params.jobId)
  }
  if (method === 'job.progress') {
    const existing = jobState.jobs[params.jobId] || ({ id: params.jobId, params: {}, checkpoint: {}, createdAt: '', updatedAt: '' } as any)
    jobState.jobs[params.jobId] = {
      ...existing,
      state: existing.state === 'waiting_rate_limit' || existing.state === 'cancelling' ? existing.state : 'running',
      progress: params,
      stage: params.stage
    } as Job
    if (!jobState.order.includes(params.jobId)) jobState.order.unshift(params.jobId)
  }
  if (method === 'job.result') {
    const existing = jobState.jobs[params.jobId]
    if (existing) {
      jobState.jobs[params.jobId] = {
        ...existing,
        state: params.error ? (existing.state === 'interrupted' ? 'interrupted' : 'failed') : 'succeeded',
        error: params.error || null
      } as Job
    }
  }
}

export function trackJob(job: Job) {
  jobState.jobs[job.id] = job
  if (!jobState.order.includes(job.id)) jobState.order.unshift(job.id)
}

export function isActive(job: Job | undefined): boolean {
  return Boolean(job && ['queued', 'running', 'waiting_rate_limit', 'cancelling'].includes(job.state))
}
