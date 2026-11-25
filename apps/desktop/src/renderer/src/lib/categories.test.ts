import { describe, expect, it } from 'vitest'
import { CATEGORIES, bytesLabel, categoryMeta, durationLabel, timecode } from './categories'

describe('category map', () => {
  it('covers all nine candidate categories with colour and glyph metadata', () => {
    expect(Object.keys(CATEGORIES)).toHaveLength(9)
    for (const meta of Object.values(CATEGORIES)) {
      expect(meta.color).toMatch(/^#[0-9a-f]{6}$/i)
      expect(meta.label.length).toBeGreaterThan(2)
      expect(meta.icon.length).toBeGreaterThan(2)
    }
  })

  it('falls back safely for unknown model output', () => {
    const meta = categoryMeta('not_a_real_category')
    expect(meta.label).toBe('not a real category')
    expect(meta.icon).toBe('spark')
  })
})

describe('time and size labels', () => {
  it('formats timecodes with and without milliseconds', () => {
    expect(timecode(0)).toBe('00:00')
    expect(timecode(65)).toBe('01:05')
    expect(timecode(3665)).toBe('1:01:05')
    expect(timecode(65.5, true)).toBe('01:05.50')
    expect(timecode(-3)).toBe('00:00')
  })

  it('formats durations and bytes for humans', () => {
    expect(durationLabel(42)).toBe('42s')
    expect(durationLabel(125)).toBe('2m 5s')
    expect(durationLabel(120)).toBe('2m')
    expect(bytesLabel(0)).toBe('—')
    expect(bytesLabel(1536)).toBe('1.5 KB')
    expect(bytesLabel(1024 * 1024 * 80)).toBe('80 MB')
  })
})
