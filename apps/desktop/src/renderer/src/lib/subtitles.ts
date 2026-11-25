export interface SubtitleWord {
  text: string
  start: number
  end: number
}

export interface SubtitleLine {
  start: number
  end: number
  words: SubtitleWord[]
}

export const SUBTITLE_MAX_CHARS = 42
export const ACTIVE_BEFORE = 0.1
export const ACTIVE_AFTER = 0.25

function time(value: unknown): number {
  const n = Number(value)
  return Number.isFinite(n) ? n : 0
}

/**
 * Words that belong to [startS, endS], clipped to that interval.
 *
 * Phrase-only transcripts (captions without word timings) are represented by
 * one word per segment. Without that fallback the Studio shows no subtitles at
 * all even though the burned renderer has a caption to show.
 */
export function subtitleWords(
  segments: readonly any[] | null | undefined,
  startS: number,
  endS: number
): SubtitleWord[] {
  const clipStart = time(startS)
  const clipEnd = time(endS)
  if (!Array.isArray(segments) || clipEnd <= clipStart) return []

  const words: SubtitleWord[] = []
  for (const segment of segments) {
    if (!segment) continue
    const segStart = time(segment.startS)
    const segEnd = time(segment.endS)
    if (segEnd <= clipStart || segStart >= clipEnd) continue

    const source = Array.isArray(segment.words) && segment.words.length
      ? segment.words
      : [{ text: segment.text, startS: segStart, endS: segEnd }]

    for (const raw of source) {
      if (!raw) continue
      const start = Math.max(clipStart, time(raw.startS ?? segStart))
      const end = Math.min(clipEnd, time(raw.endS ?? segEnd))
      const text = String(raw.text ?? '').trim()
      if (!text || end <= start) continue
      words.push({ text, start, end })
    }
  }
  words.sort((a, b) => a.start - b.start || a.end - b.end)
  return words
}

/** Group words into short display lines without splitting a word. */
export function groupSubtitleWords(
  words: readonly SubtitleWord[],
  maxChars = SUBTITLE_MAX_CHARS
): SubtitleLine[] {
  const limit = Math.max(1, Math.floor(time(maxChars) || SUBTITLE_MAX_CHARS))
  const lines: SubtitleLine[] = []
  let current: SubtitleWord[] = []
  let length = 0

  const flush = () => {
    if (!current.length) return
    lines.push({
      start: current[0].start,
      end: current[current.length - 1].end,
      words: current
    })
    current = []
    length = 0
  }

  for (const word of words) {
    if (!word.text) continue
    const addition = word.text.length + (current.length ? 1 : 0)
    if (current.length && length + addition > limit) flush()
    current.push(word)
    length += word.text.length + (current.length > 1 ? 1 : 0)
  }
  flush()
  return lines
}

/**
 * The caption line visible at an absolute source time.
 *
 * A small lead-in/lead-out tolerance keeps a line on screen while the speaker
 * crosses a word boundary instead of flickering for one video frame.
 */
export function activeSubtitleLine(
  lines: readonly SubtitleLine[],
  current: number,
  before = ACTIVE_BEFORE,
  after = ACTIVE_AFTER
): SubtitleLine | null {
  const now = time(current)
  for (const line of lines) {
    if (now >= line.start - before && now <= line.end + after) return line
  }
  return null
}

export function isActiveSubtitleWord(
  line: SubtitleLine | null,
  word: SubtitleWord,
  current: number
): boolean {
  if (!line) return false
  const index = line.words.indexOf(word)
  if (index < 0) return false
  const now = time(current)
  const next = line.words[index + 1]
  return now >= word.start && (!next || now < next.start)
}

/** Absolute source time represented by a video element's currentTime. */
export function subtitleClock(videoTime: number, videoOffset = 0): number {
  return time(videoTime) + time(videoOffset)
}
