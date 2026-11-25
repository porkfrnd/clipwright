export interface CategoryMeta {
  label: string
  color: string
  icon: string
}

export const CATEGORIES: Record<string, CategoryMeta> = {
  funny: { label: 'Funny', color: '#c9a227', icon: 'laugh' },
  educational: { label: 'Educational', color: '#6fa58a', icon: 'book' },
  storytelling: { label: 'Storytelling', color: '#9b8bc4', icon: 'spool' },
  surprising: { label: 'Surprising', color: '#c97a6a', icon: 'spark' },
  emotional: { label: 'Emotional', color: '#be7c91', icon: 'heart' },
  controversial: { label: 'Controversial', color: '#c26a4a', icon: 'split' },
  insight: { label: 'Insight', color: '#7e9fc4', icon: 'eye' },
  strong_hook: { label: 'Strong hook', color: '#d8a54b', icon: 'hook' },
  best_overall: { label: 'Best overall', color: '#c4b07a', icon: 'star' }
}

export function categoryMeta(name: string): CategoryMeta {
  return CATEGORIES[name] || { label: name.replace(/_/g, ' '), color: 'var(--text-soft)', icon: 'spark' }
}

export const RATING_LABELS: Record<string, string> = {
  hook_strength: 'Hook',
  context_completeness: 'Context',
  ending_quality: 'Ending',
  standalone_clarity: 'Clarity'
}

export function timecode(seconds: number, withMs = false): string {
  const s = Math.max(0, Number(seconds) || 0)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  if (withMs) return `${String(m).padStart(2, '0')}:${sec.toFixed(2).padStart(5, '0')}`
  return h > 0
    ? `${h}:${String(m).padStart(2, '0')}:${String(Math.floor(sec)).padStart(2, '0')}`
    : `${String(m).padStart(2, '0')}:${String(Math.floor(sec)).padStart(2, '0')}`
}

export function durationLabel(seconds: number): string {
  const s = Math.round(Number(seconds) || 0)
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  const rest = s % 60
  return rest ? `${m}m ${rest}s` : `${m}m`
}

export function bytesLabel(bytes?: number | null): string {
  if (!bytes) return '—'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let value = bytes
  let i = 0
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024
    i++
  }
  return `${value.toFixed(value >= 10 || i === 0 ? 0 : 1)} ${units[i]}`
}
