<script lang="ts">
  import {
    activeSubtitleLine,
    groupSubtitleWords,
    isActiveSubtitleWord,
    subtitleWords,
    type SubtitleWord
  } from '$lib/subtitles'

  let {
    segments = [],
    startS = 0,
    endS = 0,
    current = 0,
    style,
    scale = 0.398
  }: {
    segments: any[]
    startS: number
    endS: number
    current: number
    style: any
    /** Frame width / render width (1080). Keeps preview type at render scale. */
    scale?: number
  } = $props()

  const words = $derived(subtitleWords(segments, startS, endS))
  const grouped = $derived(groupSubtitleWords(words))
  const activeLine = $derived(activeSubtitleLine(grouped, current))

  function isActive(word: SubtitleWord): boolean {
    return isActiveSubtitleWord(activeLine, word, current)
  }

  const fontPx = $derived(Math.max(8, (Number(style?.fontSize) || 64) * scale))
  const outlinePx = $derived(Math.max(1, (Number(style?.outline) || 4) * scale))
  const shadowPx = $derived(Math.max(1, 2 * scale * 2))
</script>

{#if style?.enabled && activeLine}
  <div
    class="subtitle-preview"
    style={`z-index:3;position:absolute;left:7%;right:7%;text-align:center;pointer-events:none;font-family:'${style.font || 'Bebas Neue'}',sans-serif;font-size:${fontPx.toFixed(2)}px;line-height:1.02;letter-spacing:.02em;color:${style.color || '#fff'};text-transform:${style.uppercase ? 'uppercase' : 'none'};` +
      (style.position === 'center' ? 'top:50%;transform:translateY(-50%);' : style.position === 'bottom' ? 'bottom:8%;' : 'bottom:19%;')}
  >
    {#each activeLine.words as word}
      <span
        style={`color:${isActive(word) ? style.highlightColor || '#e8c77b' : style.color || '#fff'};` +
          `text-shadow:0 ${shadowPx.toFixed(2)}px 0 ${style.outlineColor || '#000'}, ${outlinePx.toFixed(2)}px 0 0 ${style.outlineColor || '#000'}, -${outlinePx.toFixed(2)}px 0 0 ${style.outlineColor || '#000'}, 0 -${outlinePx.toFixed(2)}px 0 ${style.outlineColor || '#000'}, 0 ${(shadowPx * 3).toFixed(2)}px ${(shadowPx * 9).toFixed(2)}px rgba(0,0,0,.65);`}
      >{word.text}</span>{' '}
    {/each}
  </div>
{/if}
