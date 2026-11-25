import type { ClipwrightApi } from './index'

declare global {
  interface Window {
    clipwright: ClipwrightApi
  }
}

export {}
