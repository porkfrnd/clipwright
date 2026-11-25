export class ApiError extends Error {
  code: string
  details?: Record<string, any>
  retryable?: boolean
  constructor(code: string, message: string, details?: Record<string, any>, retryable?: boolean) {
    super(message)
    this.code = code
    this.details = details
    this.retryable = retryable
  }
}

export async function request<T = any>(method: string, params: Record<string, any> = {}): Promise<T> {
  // Svelte 5 state proxies are not structured-cloneable. Protocol params are JSON,
  // so flatten them before they cross the contextBridge boundary.
  const plain = JSON.parse(JSON.stringify(params ?? {}))
  const response = await window.clipwright.request(method, plain)
  if (response && response.__error) {
    const err = response.__error
    throw new ApiError(err.code, err.message, err.details, err.retryable)
  }
  return response as T
}

export async function resolveAsset(assetId: string) {
  return window.clipwright.resolveAsset(assetId)
}

export function errorText(error: unknown): string {
  if (error instanceof ApiError) return error.message
  if (error instanceof Error) return error.message
  return String(error)
}

export function errorCode(error: unknown): string | null {
  if (error instanceof ApiError) return error.code
  return null
}
