import { app, safeStorage } from 'electron'
import { existsSync, readFileSync, renameSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

type Stored = Record<string, string>

export class SecretStore {
  private file = join(app.getPath('userData'), 'secrets.json')
  private stored: Stored = {}
  private session = new Map<string, string>()
  private backend = 'unknown'
  private encryptionAvailable = false
  private initialized = false

  async init(): Promise<void> {
    if (this.initialized) return
    this.initialized = true
    try {
      this.encryptionAvailable = await safeStorage.isAsyncEncryptionAvailable()
    } catch {
      this.encryptionAvailable = false
    }
    try {
      this.backend = safeStorage.getSelectedStorageBackend()
    } catch {
      this.backend = 'unknown'
    }
    if (existsSync(this.file)) {
      try {
        const raw = JSON.parse(readFileSync(this.file, 'utf8'))
        if (raw && typeof raw.entries === 'object') this.stored = raw.entries
      } catch {
        this.stored = {}
      }
    }
  }

  get weakBackend(): boolean {
    return this.backend === 'basic_text' || this.backend === 'unknown'
  }

  async status() {
    await this.init()
    return {
      available: this.encryptionAvailable,
      backend: this.backend,
      weakBackend: this.weakBackend,
      storedProfiles: Object.keys(this.stored),
      sessionProfiles: [...this.session.keys()],
      envGroq: Boolean(process.env.GROQ_API_KEY)
    }
  }

  private persist() {
    const tmp = `${this.file}.tmp`
    writeFileSync(tmp, JSON.stringify({ version: 1, entries: this.stored }), { mode: 0o600 })
    renameSync(tmp, this.file)
  }

  async setKey(profileId: string, apiKey: string, allowWeak: boolean): Promise<{ stored: boolean; sessionOnly: boolean }> {
    await this.init()
    const trimmed = (apiKey || '').trim()
    if (!trimmed) {
      await this.deleteKey(profileId)
      return { stored: false, sessionOnly: false }
    }
    if (this.encryptionAvailable && (!this.weakBackend || allowWeak)) {
      const encrypted = await safeStorage.encryptStringAsync(trimmed)
      this.stored[profileId] = encrypted.toString('base64')
      this.session.delete(profileId)
      this.persist()
      return { stored: true, sessionOnly: false }
    }
    this.session.set(profileId, trimmed)
    return { stored: false, sessionOnly: true }
  }

  async getKey(profileId: string | null | undefined): Promise<string | undefined> {
    await this.init()
    if (!profileId) return undefined
    const session = this.session.get(profileId)
    if (session) return session
    const encrypted = this.stored[profileId]
    if (!encrypted) return undefined
    if (!this.encryptionAvailable) return undefined
    try {
      const decrypted = await safeStorage.decryptStringAsync(Buffer.from(encrypted, 'base64'))
      if (decrypted.shouldReEncrypt) {
        try {
          const reencrypted = await safeStorage.encryptStringAsync(decrypted.result)
          this.stored[profileId] = reencrypted.toString('base64')
          this.persist()
        } catch {
          // keep the old ciphertext if re-encryption fails
        }
      }
      return decrypted.result
    } catch {
      delete this.stored[profileId]
      try {
        this.persist()
      } catch {
        // ignore; a corrupt entry should not block the app
      }
      return undefined
    }
  }

  async hasKey(profileId: string): Promise<boolean> {
    const key = await this.getKey(profileId)
    return Boolean(key)
  }

  async deleteKey(profileId: string): Promise<void> {
    await this.init()
    this.session.delete(profileId)
    if (profileId in this.stored) {
      delete this.stored[profileId]
      this.persist()
    }
  }
}
