import { describe, expect, it } from 'vitest'
import { PROTOCOL_VERSION, PRODUCT_NAME } from './brand'

describe('product identity', () => {
  it('is generated from the engine brand module', () => {
    expect(PRODUCT_NAME).toBe('Clipwright')
    expect(PROTOCOL_VERSION).toBe(1)
  })
})
