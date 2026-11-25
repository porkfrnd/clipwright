// Update-check logic shared by the Electron main process and the renderer.
// Keep this module free of Node and Electron imports so it stays unit-testable.

export const UPDATE_REPO = 'porkfrnd/clipwright'
export const UPDATE_RELEASES_URL = `https://github.com/${UPDATE_REPO}/releases`
export const UPDATE_API_URL = `https://api.github.com/repos/${UPDATE_REPO}/releases/latest`

export type UpdateStatus = 'idle' | 'checking' | 'available' | 'current' | 'error'

export interface UpdateAsset {
  name: string
  size: number
  url: string
  contentType?: string
}

export interface UpdateState {
  status: UpdateStatus
  currentVersion: string
  latestVersion?: string
  tagName?: string
  releaseName?: string
  releaseNotes?: string
  releaseUrl?: string
  publishedAt?: string
  assets?: UpdateAsset[]
  checkedAt?: string
  error?: string
}

export interface ParsedVersion {
  core: [number, number, number]
  prerelease: string[]
}

const VERSION_RE = /^[vV]?(\d{1,4})(?:\.(\d{1,4}))?(?:\.(\d{1,4}))?(?:-([0-9A-Za-z.-]{1,64}))?(?:\+[0-9A-Za-z.-]{1,64})?$/

export function parseVersion(input: unknown): ParsedVersion | null {
  if (typeof input !== 'string') return null
  const match = VERSION_RE.exec(input.trim())
  if (!match) return null
  return {
    core: [Number(match[1]), Number(match[2] || 0), Number(match[3] || 0)],
    prerelease: match[4] ? match[4].split('.') : []
  }
}

function comparePrerelease(a: string[], b: string[]): number {
  if (!a.length && !b.length) return 0
  if (!a.length) return 1
  if (!b.length) return -1
  const length = Math.max(a.length, b.length)
  for (let index = 0; index < length; index += 1) {
    const left = a[index]
    const right = b[index]
    if (left === undefined) return -1
    if (right === undefined) return 1
    if (left === right) continue
    const leftNumeric = /^\d+$/.test(left)
    const rightNumeric = /^\d+$/.test(right)
    if (leftNumeric && rightNumeric) return Number(left) > Number(right) ? 1 : -1
    if (leftNumeric !== rightNumeric) return leftNumeric ? -1 : 1
    return left > right ? 1 : -1
  }
  return 0
}

/** Positive when `left` is newer than `right`; 0 for equal or unparseable input. */
export function compareVersions(left: unknown, right: unknown): number {
  const a = parseVersion(left)
  const b = parseVersion(right)
  if (!a || !b) return 0
  for (let index = 0; index < 3; index += 1) {
    if (a.core[index] !== b.core[index]) return a.core[index] > b.core[index] ? 1 : -1
  }
  return comparePrerelease(a.prerelease, b.prerelease)
}

export function isNewerVersion(latest: unknown, current: unknown): boolean {
  return compareVersions(latest, current) > 0
}

function text(value: unknown, max: number): string {
  return typeof value === 'string' ? value.trim().slice(0, max) : ''
}

function allowedReleaseUrl(value: unknown): string | null {
  if (typeof value !== 'string') return null
  try {
    const url = new URL(value)
    if (url.protocol !== 'https:') return null
    if (url.hostname !== 'github.com') return null
    if (!url.pathname.startsWith(`/${UPDATE_REPO}/releases/`)) return null
    return url.toString()
  } catch {
    return null
  }
}

function allowedAssetUrl(value: unknown): string | null {
  if (typeof value !== 'string') return null
  try {
    const url = new URL(value)
    if (url.protocol !== 'https:') return null
    if (url.hostname !== 'github.com' && !url.hostname.endsWith('.githubusercontent.com')) return null
    return url.toString()
  } catch {
    return null
  }
}

export function releaseToUpdate(payload: unknown, currentVersion: string): UpdateState {
  if (!payload || typeof payload !== 'object') throw new Error('GitHub sent an unexpected response.')
  const release = payload as Record<string, unknown>
  const tagName = text(release.tag_name, 64)
  if (!parseVersion(tagName)) throw new Error('GitHub sent a release without a usable version.')
  const version = tagName.replace(/^[vV]/, '')
  const releaseUrl =
    allowedReleaseUrl(release.html_url) ||
    `${UPDATE_RELEASES_URL}/tag/${encodeURIComponent(tagName)}`
  const rawAssets = Array.isArray(release.assets) ? release.assets : []
  const assets: UpdateAsset[] = []
  for (const raw of rawAssets.slice(0, 20)) {
    if (!raw || typeof raw !== 'object') continue
    const asset = raw as Record<string, unknown>
    const name = text(asset.name, 180)
    const url = allowedAssetUrl(asset.browser_download_url)
    if (!name || !url) continue
    const size = Number(asset.size)
    assets.push({
      name,
      url,
      size: Number.isFinite(size) && size > 0 ? size : 0,
      contentType: text(asset.content_type, 120) || undefined
    })
  }
  return {
    status: isNewerVersion(tagName, currentVersion) ? 'available' : 'current',
    currentVersion,
    latestVersion: version,
    tagName,
    releaseName: text(release.name, 180) || tagName,
    releaseNotes: text(release.body, 14000),
    releaseUrl,
    publishedAt: text(release.published_at, 40) || undefined,
    assets,
    checkedAt: new Date().toISOString()
  }
}

export function idleUpdateState(currentVersion: string): UpdateState {
  return { status: 'idle', currentVersion }
}

export function errorUpdateState(currentVersion: string, message: string): UpdateState {
  return { status: 'error', currentVersion, error: message.slice(0, 300), checkedAt: new Date().toISOString() }
}

/** Pick the release asset that matches the host, with a sensible fallback. */
export function chooseAsset(assets: UpdateAsset[] | undefined, platform: string, arch: string): UpdateAsset | null {
  if (!assets?.length) return null
  const wantedArch = /arm|aarch/i.test(arch) ? 'arm64' : 'x64'
  const archPattern = wantedArch === 'arm64' ? /(arm64|aarch64)/i : /(x86_64|x64|amd64)/i
  const platformPatterns: Record<string, RegExp[]> = {
    linux: [/\.AppImage$/i, /\.deb$/i, /\.rpm$/i, /\.tar\.gz$/i],
    win32: [/\.exe$/i, /\.msi$/i, /\.zip$/i],
    darwin: [/\.dmg$/i, /\.pkg$/i, /\.zip$/i]
  }
  const patterns = platformPatterns[platform] || []
  for (const pattern of patterns) {
    const match = assets.find((asset) => pattern.test(asset.name) && archPattern.test(asset.name))
    if (match) return match
  }
  for (const pattern of patterns) {
    const match = assets.find((asset) => pattern.test(asset.name))
    if (match) return match
  }
  return null
}
