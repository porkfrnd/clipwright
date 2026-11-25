<script lang="ts">
  import type { Candidate } from '$shared/types'
  import { RATING_LABELS, categoryMeta, timecode, durationLabel } from '$lib/categories'
  import Icon from './Icon.svelte'
  import Meter from './Meter.svelte'
  import CategoryPill from './CategoryPill.svelte'

  let {
    candidate,
    selected = false,
    onToggle,
    onPreview,
    onReject
  }: {
    candidate: Candidate
    selected?: boolean
    onToggle?: (candidate: Candidate) => void
    onPreview?: (candidate: Candidate) => void
    onReject?: (candidate: Candidate) => void
  } = $props()

  let expanded = $state(false)
  const categories = $derived((candidate.categories?.length ? candidate.categories : [candidate.category]).slice(0, 3))
</script>

<article class={`candidate-card ${selected ? 'selected' : ''} ${candidate.status === 'rejected' ? 'rejected' : ''}`}>
  <div class="row" style="align-items:flex-start">
    <div style="flex:1;min-width:0;display:grid;gap:8px">
      <div class="row tight">
        {#each categories as cat}
          <CategoryPill category={cat} small />
        {/each}
      </div>
      <div class="title">{candidate.title}</div>
    </div>
    <div class="fit-badge" style={`--fit:${candidate.fitScore}`} title="Clip fit: how well this clip meets the criteria. Not a prediction of views.">
      <span>{Math.round(candidate.fitScore)}</span>
    </div>
  </div>

  <div class="row" style="justify-content:space-between">
    <span class="timecode">{timecode(candidate.startS)} → {timecode(candidate.endS)}</span>
    <span class="tag">{durationLabel(candidate.durationS)}</span>
  </div>

  <p class="excerpt">{candidate.excerpt || candidate.rationale}</p>

  <div class="rating-grid">
    {#each Object.entries(candidate.ratings || {}) as [key, rating]}
      <Meter value={rating.score} label={RATING_LABELS[key] || key} evidence={rating.evidence} />
    {/each}
  </div>

  {#if expanded}
    <div class="stack" style="gap:10px;border-top:1px solid var(--hairline);padding-top:12px">
      <div>
        <div class="eyebrow" style="margin-bottom:4px">Why this was picked</div>
        <p class="small soft">{candidate.rationale}</p>
      </div>
      {#if candidate.weaknesses?.length}
        <div>
          <div class="eyebrow" style="margin-bottom:4px">Weaknesses</div>
          <div class="weaknesses">
            {#each candidate.weaknesses as weakness}<span>{weakness}</span>{/each}
          </div>
        </div>
      {/if}
      <div class="row tiny muted">
        <span>{candidate.signals?.wordCount ?? 0} words</span>
        <span>·</span>
        <span>{candidate.signals?.sentenceAlignedEnd ? 'sentence-aligned ending' : 'ending needs a check'}</span>
        {#if candidate.signals?.speechContinuity != null}
          <span>·</span><span>{Math.round(candidate.signals.speechContinuity * 100)}% speech coverage</span>
        {/if}
      </div>
    </div>
  {/if}

  <div class="row" style="justify-content:space-between">
    <div class="row tight">
      {#if onPreview}
        <button class="btn ghost sm" onclick={() => onPreview(candidate)}>
          <Icon name="play" size={13} /> Preview
        </button>
      {/if}
      <button class="link tiny" onclick={() => (expanded = !expanded)}>{expanded ? 'Less' : 'Details'}</button>
    </div>
    <div class="row tight">
      {#if onReject}
        <button class="icon-btn" title="Not this one" onclick={() => onReject(candidate)} style="width:32px;height:32px">
          <Icon name="x" size={14} />
        </button>
      {/if}
      {#if onToggle}
        <button class={`btn sm ${selected ? 'primary' : 'ghost'}`} onclick={() => onToggle(candidate)}>
          <Icon name={selected ? 'check' : 'plus'} size={13} /> {selected ? 'Selected' : 'Select'}
        </button>
      {/if}
    </div>
  </div>
</article>
