import { describe, expect, it } from 'vitest'
import {
  chooseAsset,
  compareVersions,
  isNewerVersion,
  parseVersion,
  releaseToUpdate
} from './updates'

const release = {
  tag_name: 'v0.2.0',
  name: 'Clipwright 0.2.0',
  body: 'Faster discovery and a calmer update flow.',
  html_url: 'https://github.com/porkfrnd/clipwright/releases/tag/v0.2.0',
  published_at: '2026-11-25T10:00:00Z',
  assets: [
    {
      name: 'Clipwright-0.2.0-x86_64.AppImage',
      size: 500000000,
      content_type: 'application/octet-stream',
      browser_download_url:
        'https://github.com/porkfrnd/clipwright/releases/download/v0.2.0/Clipwright-0.2.0-x86_64.AppImage'
    },
    { name: 'notes.txt', size: 10, browser_download_url: 'https://example.com/notes.txt' }
  ]
}

describe('version parsing and comparison', () => {
  it('accepts v-prefixed and partial versions', () => {
    expect(parseVersion('v1.2.3')).toEqual({ core: [1, 2, 3], prerelease: [] })
    expect(parseVersion('1.2')).toEqual({ core: [1, 2, 0], prerelease: [] })
    expect(parseVersion('nope')).toBeNull()
  })

  it('orders stable versions numerically, not lexically', () => {
    expect(compareVersions('0.10.0', '0.9.9')).toBeGreaterThan(0)
    expect(compareVersions('v0.2.0', '0.2.0')).toBe(0)
    expect(isNewerVersion('0.2.0', '0.1.9')).toBe(true)
    expect(isNewerVersion('0.1.9', '0.2.0')).toBe(false)
  })

  it('orders prereleases below the stable release', () => {
    expect(compareVersions('1.0.0', '1.0.0-rc.1')).toBeGreaterThan(0)
    expect(compareVersions('1.0.0-rc.2', '1.0.0-rc.1')).toBeGreaterThan(0)
    expect(compareVersions('1.0.0-alpha', '1.0.0-alpha.1')).toBeLessThan(0)
  })

  it('never prompts for unparseable versions', () => {
    expect(isNewerVersion('latest', '0.1.0')).toBe(false)
    expect(isNewerVersion('0.2.0', 'development')).toBe(false)
  })
})

describe('release mapping', () => {
  it('maps a newer release and keeps only safe GitHub asset links', () => {
    const state = releaseToUpdate(release, '0.1.0')
    expect(state.status).toBe('available')
    expect(state.latestVersion).toBe('0.2.0')
    expect(state.tagName).toBe('v0.2.0')
    expect(state.assets).toHaveLength(1)
    expect(state.assets?.[0].name).toContain('AppImage')
  })

  it('reports current when the tag is not newer', () => {
    expect(releaseToUpdate(release, '0.2.0').status).toBe('current')
    expect(releaseToUpdate(release, '1.0.0').status).toBe('current')
  })

  it('rejects a release URL outside this repository', () => {
    const state = releaseToUpdate(
      { ...release, html_url: 'https://github.com/someone/else/releases/tag/v9.9.9' },
      '0.1.0'
    )
    expect(state.releaseUrl).toBe('https://github.com/porkfrnd/clipwright/releases/tag/v0.2.0')
  })

  it('rejects malformed releases', () => {
    expect(() => releaseToUpdate(null, '0.1.0')).toThrow()
    expect(() => releaseToUpdate({ tag_name: 'not-a-version' }, '0.1.0')).toThrow()
  })

  it('caps long notes rather than trusting the API blindly', () => {
    const state = releaseToUpdate({ ...release, body: 'x'.repeat(50000) }, '0.1.0')
    expect(state.releaseNotes?.length).toBe(14000)
  })
})

describe('asset selection', () => {
  const assets = releaseToUpdate(release, '0.1.0').assets || []

  it('prefers an AppImage for Linux x64', () => {
    expect(chooseAsset(assets, 'linux', 'x64')?.name).toContain('AppImage')
  })

  it('falls back to the platform pattern without an arch match', () => {
    const arm = [{ name: 'Clipwright-0.2.0-x86_64.AppImage', size: 1, url: 'https://github.com/x' }]
    expect(chooseAsset(arm, 'linux', 'arm64')?.name).toContain('AppImage')
  })

  it('returns null when no asset fits', () => {
    expect(chooseAsset(assets, 'darwin', 'arm64')).toBeNull()
    expect(chooseAsset([], 'linux', 'x64')).toBeNull()
  })
})
