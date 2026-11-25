import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, errorCode, errorText, request } from './api'

function setBridge(fn: (method: string, params: Record<string, any>) => Promise<any>) {
  ;(globalThis as any).window = { clipwright: { request: fn } }
}

afterEach(() => {
  delete (globalThis as any).window
})

describe('renderer api bridge', () => {
  it('unwraps engine results', async () => {
    const bridge = vi.fn(async () => ({ project: { id: 'p1' } }))
    setBridge(bridge)
    const result = await request('project.create', { name: 'x' })
    expect(result.project.id).toBe('p1')
    expect(bridge).toHaveBeenCalledWith('project.create', { name: 'x' })
  })

  it('converts an engine error envelope into ApiError', async () => {
    setBridge(async () => ({ __error: { code: 'PROVIDER_AUTH_FAILED', message: 'Bad key', details: { a: 1 }, retryable: false } }))
    await expect(request('provider.test', {})).rejects.toMatchObject({ code: 'PROVIDER_AUTH_FAILED', message: 'Bad key' })
    try {
      await request('provider.test', {})
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError)
      expect(errorCode(error)).toBe('PROVIDER_AUTH_FAILED')
      expect(errorText(error)).toBe('Bad key')
    }
  })

  it('flattens Svelte-like proxies before crossing the context bridge', async () => {
    let received: any
    setBridge(async (_method, params) => {
      received = params
      return { ok: true }
    })
    const state = new Proxy({ nested: new Proxy({ value: 4 }, {}) }, {})
    await request('settings.set', state as any)
    expect(received).toEqual({ nested: { value: 4 } })
    expect(Object.getPrototypeOf(received)).toBe(Object.prototype)
  })

  it('formats unknown errors without leaking a stack', () => {
    expect(errorText(new Error('plain'))).toBe('plain')
    expect(errorText('oops')).toBe('oops')
    expect(errorCode(new Error('plain'))).toBeNull()
  })
})
