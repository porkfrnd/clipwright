export type EngineStatus = 'starting' | 'ready' | 'restarting' | 'failed' | 'stopped'

export interface EngineEvent {
  v: number
  id?: string
  kind: 'event'
  method: string
  params: Record<string, any>
}

export interface EngineResponse<T = any> {
  v: number
  id: string
  kind: 'response'
  result?: T
  error?: {
    code: string
    message: string
    details?: Record<string, any>
    retryable?: boolean
  }
}

export interface SourceSummary {
  id: string
  projectId: string
  kind: 'url' | 'file'
  url?: string | null
  localPath?: string | null
  title: string
  channel?: string | null
  durationS?: number | null
  width?: number | null
  height?: number | null
  fps?: number | null
  language?: string | null
  createdAt: string
  mediaUrl?: string
}

export interface Candidate {
  id: string
  sourceId: string
  analysisRunId: string
  category: string
  categories: string[]
  startS: number
  endS: number
  durationS: number
  title: string
  excerpt: string
  rationale: string
  ratings: Record<string, { score: number; evidence: string }>
  weaknesses: string[]
  fitScore: number
  signals: Record<string, any>
  segStartKey: string
  segEndKey: string
  status: string
  rank?: number | null
  revisions?: { startS: number; endS: number; by: string; createdAt: string }[]
}

export interface Selection {
  id: string
  projectId: string
  candidateId: string
  position: number
  presetId?: string | null
  candidate: Candidate
  edit: EditSettings
}

export interface EditSettings {
  framing: {
    layout: 'fill' | 'blur' | 'manual'
    faceTracking: boolean
    zoom: number
    manual?: Record<string, number> | null
  }
  subtitles: {
    enabled: boolean
    mode: string
    font: string
    fontSize: number
    color: string
    highlightColor: string
    outlineColor: string
    outline: number
    shadow: number
    background: boolean
    position: 'lower_third' | 'bottom' | 'center'
    maxLines: number
    uppercase: boolean
    hideFillers: boolean
    offsetMs: number
    lineOffsetsMs: Record<string, number>
    safeZone: "none" | "tiktok" | "reels" | "shorts"
    safePreset: string
    tighten: {
      enabled: boolean
      pauseThresholdS: number
      minPauseS: number
      removeFillers: boolean
    }
  }
  effects: {
    enabled: boolean
    fade: boolean
    progressBar: boolean
    cinematic: boolean
    zoomPunch: boolean
  }
  audio: {
    loudnessTarget: number
    truePeak: number
    denoise: boolean
    voiceEnhance: boolean
    musicPath: string | null
    musicGainDb: number
    ducking: boolean
  }
  metadata: { title: string; description: string; hashtags: string[] }
}

export interface Project {
  id: string
  name: string
  createdAt: string
  updatedAt: string
  lastOpenedAt?: string | null
  state: string
  counts?: { sources: number; selections: number; exports: number }
  sources?: SourceSummary[]
}

export interface ProviderProfile {
  id: string
  name: string
  adapter: 'groq' | 'openai_compatible' | 'custom' | 'local'
  baseUrl: string
  defaultModel?: string | null
  capabilities: Record<string, any>
  enabled: boolean
  default?: boolean
  envKeyAvailable?: boolean
}

export interface Job {
  id: string
  projectId?: string | null
  type: string
  state: 'queued' | 'running' | 'paused' | 'waiting_rate_limit' | 'cancelling' | 'cancelled' | 'failed' | 'succeeded' | 'interrupted'
  stage?: string | null
  params: Record<string, any>
  checkpoint: Record<string, any>
  error?: { code: string; message: string; details?: any; retryable?: boolean } | null
  progress?: { stage?: string; fraction?: number; message?: string; etaSeconds?: number }
  createdAt: string
  updatedAt: string
}

export interface AppSettings {
  app: {
    theme: 'velvet' | 'ember' | 'ivory' | 'slate'
    appearance: 'dark' | 'light'
    density: 'comfortable' | 'compact'
    reduceMotion: boolean
    effects: boolean
  }
  transcription: {
    engine: 'local_whisper' | 'cloud_openai'
    localModel: string
    cloudModel: string
    providerProfileId?: string | null
    preferCaptions: boolean
    language?: string | null
  }
  analysis: {
    maxCandidatesPerWindow: number
    windowSeconds: number
    overlap: number
    minDuration: number
    maxDuration: number
    rankWithAi: boolean
    visionEnabled: boolean
  }
  render: {
    quality: 'standard' | 'high'
    preferHardware: boolean
    filenameTemplate: string
    fps: number
    outputDir?: string
  }
  privacy: {
    authorizationAcknowledgedAt?: string | null
    providerDisclosureAt?: string | null
    requestLogEnabled: boolean
  }
  wizard: { completed: boolean }
  hardware: { profile: string }
  downloads: { channel: 'stable' | 'nightly'; autoUpdateYtdlp: boolean }
  providers?: { defaultProfileId?: string | null }
  dataDir?: string
}

export interface HardwareReport {
  os: string
  arch: string
  cpuModel?: string | null
  cores: number
  ramBytes?: number | null
  freeDiskBytes: number
  gpus: { name: string; memoryMb?: number | null; cuda?: boolean }[]
  cudaUsable: boolean
  hardwareEncoders: { name: string; ok: boolean; note?: string }[]
  usableHardwareEncoder?: string | null
  recommendedProfile: 'low' | 'balanced' | 'performance'
  profiles: { id: string; name: string; summary: string; details: string[] }[]
  dataDir: string
}
