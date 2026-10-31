import { afterEach, describe, expect, it, vi } from 'vitest'
import { createRequestId } from './requestId'

const getRandomValues = globalThis.crypto.getRandomValues.bind(globalThis.crypto)
afterEach(() => vi.unstubAllGlobals())

describe('interview request IDs', () => {
  it('creates a UUID v4 from secure random bytes without randomUUID', () => {
    const getRandomValues = vi.fn((bytes: Uint8Array) => {
      bytes.set(Array.from({ length: 16 }, (_, index) => index))
      return bytes
    })
    vi.stubGlobal('crypto', { getRandomValues })
    expect(createRequestId()).toBe('00010203-0405-4607-8809-0a0b0c0d0e0f')
    expect(getRandomValues).toHaveBeenCalledOnce()
    expect(getRandomValues.mock.calls[0][0]).toBeInstanceOf(Uint8Array)
  })

  it('preserves a secure random source failure instead of inventing a request ID', () => {
    const failure = new Error('random source unavailable')
    vi.stubGlobal('crypto', { getRandomValues: () => { throw failure } })
    expect(() => createRequestId()).toThrow(failure)
  })

  it('generates distinct valid UUIDs for new requests using the browser random source', () => {
    vi.stubGlobal('crypto', { getRandomValues })
    const ids = Array.from({ length: 1000 }, () => createRequestId())
    expect(new Set(ids).size).toBe(ids.length)
    for (const id of ids) expect(id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/)
  })
})
