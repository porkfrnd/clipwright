<script lang="ts">
  import type { Candidate } from '$shared/types'
  import { categoryMeta, timecode } from '$lib/categories'

  let {
    duration = 1,
    candidates = [],
    segments = [],
    playhead = 0,
    selectedIds = [],
    onSeek,
    onPick
  }: {
    duration: number
    candidates: Candidate[]
    segments: { startS: number; endS: number; text: string }[]
    playhead?: number
    selectedIds?: string[]
    onSeek?: (time: number) => void
    onPick?: (candidate: Candidate | null) => void
  } = $props()

  const W = 1000
  const H = 128
  const span = $derived(Math.max(1, duration))
  const x = (t: number) => (Math.max(0, Math.min(span, t)) / span) * W

  let hovered = $state<Candidate | null>(null)

  function click(event: MouseEvent) {
    const target = event.currentTarget as SVGSVGElement
    const rect = target.getBoundingClientRect()
    const ratio = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width))
    onSeek?.(ratio * span)
  }

  const density = $derived(
    segments.map((s) => {
      const width = Math.max(1.2, x(s.endS) - x(s.startS) - 0.6)
      const height = Math.min(38, 4 + Math.sqrt((s.text || '').length) * 2.2)
      return { x: x(s.startS), width, height }
    })
  )
</script>

<div class="moment-map">
  <svg
    viewBox={`0 0 ${W} ${H}`}
    role="slider"
    aria-label="Moment map showing all candidate clips across the source"
    aria-valuemin="0"
    aria-valuemax={duration}
    aria-valuenow={playhead}
    onclick={click}
    onkeydown={(e) => {
      if (e.key === 'ArrowRight') onSeek?.(Math.min(span, playhead + 5))
      if (e.key === 'ArrowLeft') onSeek?.(Math.max(0, playhead - 5))
      if (e.key === 'Home') onSeek?.(0)
      if (e.key === 'End') onSeek?.(span)
    }}
    tabindex="0"
  >
    <line x1="0" y1={H - 44} x2={W} y2={H - 44} stroke="var(--hairline)" stroke-width="1" />
    {#each density as bar}
      <rect x={bar.x} y={H - 44 - bar.height} width={bar.width} height={bar.height} rx="1" fill="var(--surface-3)" opacity="0.85" />
    {/each}

    {#each candidates as cand (cand.id)}
      {@const meta = categoryMeta(cand.category)}
      {@const tickH = 10 + (cand.fitScore / 100) * 34}
      {@const isSelected = selectedIds.includes(cand.id)}
      <g
        class="map-tick"
        role="button"
        tabindex="0"
        aria-label={`Clip moment: ${cand.title}`}
        ontouchstart={() => (hovered = cand)}
        onmouseenter={() => (hovered = cand)}
        onmouseleave={() => (hovered = null)}
        onclick={(e) => {
          e.stopPropagation()
          onPick?.(cand)
          onSeek?.(cand.startS)
        }}
        onkeydown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            onPick?.(cand)
            onSeek?.(cand.startS)
          }
        }}
        style="cursor:pointer"
      >
        <rect
          x={x(cand.startS)}
          y={30 - tickH / 2}
          width={Math.max(5, x(cand.endS) - x(cand.startS))}
          height={tickH}
          rx="2.5"
          fill={meta.color}
          opacity={isSelected ? 1 : 0.82}
          stroke={isSelected ? 'var(--text)' : 'transparent'}
          stroke-width="1.4"
        />
        <title>{cand.title} · {timecode(cand.startS)}–{timecode(cand.endS)} · fit {Math.round(cand.fitScore)}</title>
      </g>
    {/each}

    <line x1={x(playhead)} y1="8" x2={x(playhead)} y2={H - 34} stroke="var(--accent)" stroke-width="1.6" />
    <circle cx={x(playhead)} cy="8" r="3" fill="var(--accent)" />
  </svg>
  <div class="map-meta">
    <span>00:00</span>
    {#if hovered}
      <span class="gold">{hovered.title} · fit {Math.round(hovered.fitScore)}</span>
    {:else}
      <span>{candidates.length} moment{candidates.length === 1 ? '' : 's'} found</span>
    {/if}
    <span>{timecode(span)}</span>
  </div>
</div>
