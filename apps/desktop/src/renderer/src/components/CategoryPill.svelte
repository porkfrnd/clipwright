<script lang="ts">
  import Icon from './Icon.svelte'
  import { categoryMeta } from '$lib/categories'

  let { category, small = false }: { category: string; small?: boolean } = $props()
  const meta = $derived(categoryMeta(category))
</script>

<span class={`pill cat ${small ? 'tiny' : ''}`} style={`--cat-color:${meta.color}`} title={meta.label}>
  <span class="glyph"><Icon name={meta.icon} size={small ? 11 : 13} /></span>
  {meta.label}
</span>
