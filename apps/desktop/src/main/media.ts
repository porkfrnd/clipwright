import { protocol } from 'electron'
import { createReadStream, statSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { Readable } from 'node:stream'
import { extname } from 'node:path'

interface MediaEntry {
  path: string
  mime: string
}

const registry = new Map<string, MediaEntry>()

const MIME: Record<string, string> = {
  '.mp4': 'video/mp4',
  '.m4v': 'video/mp4',
  '.webm': 'video/webm',
  '.mkv': 'video/x-matroska',
  '.mov': 'video/quicktime',
  '.mp3': 'audio/mpeg',
  '.m4a': 'audio/mp4',
  '.flac': 'audio/flac',
  '.wav': 'audio/wav',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.png': 'image/png',
  '.webp': 'image/webp'
}

export function registerMedia(path: string, mime?: string): string {
  const id = createHash('sha256').update(path).digest('hex').slice(0, 32)
  registry.set(id, { path, mime: mime || MIME[extname(path).toLowerCase()] || 'application/octet-stream' })
  return `media://asset/${id}`
}

export function registerScheme() {
  protocol.registerSchemesAsPrivileged([
    {
      scheme: 'media',
      privileges: { standard: true, secure: true, supportFetchAPI: true, stream: true, corsEnabled: true }
    }
  ])
}

function rangeHeader(range: string | null, size: number): { start: number; end: number } | null {
  if (!range) return null
  const match = /^bytes=(\d*)-(\d*)$/.exec(range.trim())
  if (!match) return null
  let start = match[1] ? Number(match[1]) : 0
  let end = match[2] ? Number(match[2]) : size - 1
  if (!match[1] && match[2]) {
    start = Math.max(0, size - Number(match[2]))
    end = size - 1
  }
  if (!Number.isFinite(start) || !Number.isFinite(end) || start < 0 || start >= size || end < start) return null
  return { start, end: Math.min(end, size - 1) }
}

export function installMediaProtocol() {
  protocol.handle('media', async (request) => {
    const url = new URL(request.url)
    const id = url.pathname.replace(/^\//, '')
    const entry = registry.get(id)
    if (!entry) return new Response('Not found', { status: 404 })
    if (request.method !== 'GET' && request.method !== 'HEAD') return new Response('Method not allowed', { status: 405 })
    let size: number
    try {
      const stat = statSync(entry.path)
      if (!stat.isFile()) throw new Error('not a file')
      size = stat.size
    } catch {
      return new Response('Not found', { status: 404 })
    }
    const baseHeaders: Record<string, string> = {
      'Content-Type': entry.mime,
      'Accept-Ranges': 'bytes',
      'Cache-Control': 'no-store',
      'X-Content-Type-Options': 'nosniff',
      'Content-Security-Policy': "default-src 'none'"
    }
    const range = rangeHeader(request.headers.get('range'), size)
    if (range) {
      const length = range.end - range.start + 1
      if (request.method === 'HEAD') {
        return new Response(null, {
          status: 206,
          headers: { ...baseHeaders, 'Content-Length': String(length), 'Content-Range': `bytes ${range.start}-${range.end}/${size}` }
        })
      }
      const stream = createReadStream(entry.path, { start: range.start, end: range.end })
      return new Response(Readable.toWeb(stream) as ReadableStream, {
        status: 206,
        headers: { ...baseHeaders, 'Content-Length': String(length), 'Content-Range': `bytes ${range.start}-${range.end}/${size}` }
      })
    }
    if (request.method === 'HEAD') {
      return new Response(null, { status: 200, headers: { ...baseHeaders, 'Content-Length': String(size) } })
    }
    return new Response(Readable.toWeb(createReadStream(entry.path)) as ReadableStream, {
      status: 200,
      headers: { ...baseHeaders, 'Content-Length': String(size) }
    })
  })
}
