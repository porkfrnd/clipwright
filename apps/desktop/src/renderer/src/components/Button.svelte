<script lang="ts">
  let {
    variant = 'default',
    size = '',
    disabled = false,
    type = 'button',
    title = '',
    onclick,
    style = '',
    children
  }: {
    variant?: 'default' | 'primary' | 'ghost' | 'danger'
    size?: '' | 'sm' | 'lg'
    disabled?: boolean
    type?: 'button' | 'submit'
    title?: string
    onclick?: (event: MouseEvent) => void
    style?: string
    children?: any
  } = $props()
</script>

<button class={`btn ${variant} ${size}`} {disabled} {type} {title} {onclick} {style}>
  {@render children?.()}
</button>
