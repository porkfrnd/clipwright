<script lang="ts">
  import Icon from './Icon.svelte'

  let { value, label = '', evidence = '', max = 5 }: { value: number; label?: string; evidence?: string; max?: number } = $props()
  let show = $state(false)
</script>

<div class="meter">
  <div class="meter-top">
    <span>{label}</span>
    <strong class="mono">{value}/{max}</strong>
  </div>
  <div class="meter-track" aria-hidden="true">
    <div class="meter-fill" style={`width:${(value / max) * 100}%`}></div>
  </div>
  {#if evidence}
    <button class="link tiny" style="justify-self:start;color:var(--faint)" onclick={() => (show = !show)}>
      {show ? 'hide evidence' : 'why'}
    </button>
    {#if show}<div class="meter evidence">{evidence}</div>{/if}
  {/if}
</div>
