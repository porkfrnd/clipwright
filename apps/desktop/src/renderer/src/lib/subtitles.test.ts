import { describe, expect, it } from 'vitest'
import {
  activeSubtitleLine,
  groupSubtitleWords,
  isActiveSubtitleWord,
  subtitleClock,
  subtitleWords
} from './subtitles'

function words() {
  return [
    { text: 'One', start: 10, end: 10.5 },
    { text: 'two', start: 10.5, end: 11 },
    { text: 'three', start: 12, end: 12.5 },
    { text: 'four', start: 12.5, end: 13 }
  ]
}

describe('subtitleWords', () => {
  it('filters and clips words to the candidate range', () => {
    const result = subtitleWords(
      [
        {
          startS: 99,
          endS: 104,
          words: [
            { text: 'before', startS: 99.2, endS: 100.4 },
            { text: 'inside', startS: 100.4, endS: 101.2 }
          ]
        },
        { startS: 110, endS: 112, words: [{ text: 'after', startS: 110, endS: 111 }] }
      ],
      100.5,
      102
    )
    expect(result).toEqual([{ text: 'inside', start: 100.5, end: 101.2 }])
  })

  it('falls back to phrase text when a transcript has no word timings', () => {
    const result = subtitleWords(
      [{ startS: 100, endS: 104, text: '  A phrase without word timing.  ' }],
      100,
      104
    )
    expect(result).toEqual([{ text: 'A phrase without word timing.', start: 100, end: 104 }])
    expect(activeSubtitleLine(groupSubtitleWords(result), 101)).not.toBeNull()
  })

  it('sorts unordered words and excludes empty or inverted ranges', () => {
    const result = subtitleWords(
      [
        {
          startS: 1,
          endS: 4,
          words: [
            { text: 'second', startS: 2, endS: 3 },
            { text: '   ', startS: 1, endS: 1.5 },
            { text: 'inverted', startS: 3, endS: 2.5 },
            { text: 'first', startS: 1, endS: 1.5 }
          ]
        }
      ],
      1,
      4
    )
    expect(result.map((w) => w.text)).toEqual(['first', 'second'])
  })

  it('handles a missing or empty transcript without throwing', () => {
    expect(subtitleWords(null, 0, 10)).toEqual([])
    expect(subtitleWords([], 0, 10)).toEqual([])
    expect(subtitleWords([{ startS: 0, endS: 10, text: '', words: [] }], 0, 10)).toEqual([])
  })
})

describe('groupSubtitleWords', () => {
  it('wraps at the requested width and preserves line timing', () => {
    const result = groupSubtitleWords(
      [
        { text: 'aaaa', start: 1, end: 2 },
        { text: 'bbbb', start: 2, end: 3 },
        { text: 'cccc', start: 3, end: 4 },
        { text: 'dddd', start: 4, end: 5 }
      ],
      10
    )
    expect(result.map((line) => line.words.map((w) => w.text))).toEqual([
      ['aaaa', 'bbbb'],
      ['cccc', 'dddd']
    ])
    expect(result[0]).toMatchObject({ start: 1, end: 3 })
    expect(result[1]).toMatchObject({ start: 3, end: 5 })
  })

  it('never splits a single word longer than the limit', () => {
    const result = groupSubtitleWords([{ text: 'supercalifragilistic', start: 1, end: 2 }], 5)
    expect(result).toHaveLength(1)
    expect(result[0].words[0].text).toBe('supercalifragilistic')
  })
})

describe('activeSubtitleLine and word highlighting', () => {
  const lines = groupSubtitleWords(words(), 12)

  it('shows a line inside its range and during the small lead-in/out', () => {
    expect(activeSubtitleLine(lines, 10.5)).toBe(lines[0])
    expect(activeSubtitleLine(lines, 9.9)).toBe(lines[0])
    expect(activeSubtitleLine(lines, 13.25)).toBe(lines[1])
  })

  it('returns null in a gap and after the tail tolerance', () => {
    expect(activeSubtitleLine(lines, 11.5)).toBeNull()
    expect(activeSubtitleLine(lines, 13.26)).toBeNull()
  })

  it('highlights one word at a time and moves at the next word start', () => {
    const line = lines[0]
    expect(isActiveSubtitleWord(line, line.words[0], 10)).toBe(true)
    expect(isActiveSubtitleWord(line, line.words[1], 10)).toBe(false)
    expect(isActiveSubtitleWord(line, line.words[0], 10.5)).toBe(false)
    expect(isActiveSubtitleWord(line, line.words[1], 10.5)).toBe(true)
    expect(isActiveSubtitleWord(line, line.words[1], 10.99)).toBe(true)
  })

  it('returns false for a word from another line', () => {
    expect(isActiveSubtitleWord(lines[0], lines[1].words[0], 12)).toBe(false)
    expect(isActiveSubtitleWord(null, lines[0].words[0], 10)).toBe(false)
  })
})

describe('subtitleClock', () => {
  it('converts a section-relative video clock into source time for URL previews', () => {
    expect(subtitleClock(2, 558.11)).toBeCloseTo(560.11, 5)
    expect(activeSubtitleLine(groupSubtitleWords(words()), subtitleClock(2, 8))).not.toBeNull()
  })

  it('keeps local-file absolute time unchanged', () => {
    expect(subtitleClock(560.11, 0)).toBe(560.11)
  })
})
