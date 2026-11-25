<script lang="ts">
  let { size = 38 }: { size?: number } = $props()
</script>

<img class="brand-glyph" src="./brand.svg" width={size} height={size} alt="" aria-hidden="true" />

<style>
  .brand-glyph {
    display: block;
    flex: none;
    border-radius: 26%;
  }
</style>
