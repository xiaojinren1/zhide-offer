import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from './api'
import { migrateLegacyModel } from './modelStorage'

vi.mock('./api', () => ({ api: { modelPreference: vi.fn(), activateModel: vi.fn() } }))

const storageKey = 'jobagent:text-model:owner'
const legacy = { provider: 'deepseek', model: 'demo', api_key: 'dummy-key' }

function setup() {
  const entries = new Map([[storageKey, JSON.stringify(legacy)]])
  vi.stubGlobal('window', { isSecureContext: true })
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => entries.get(key) ?? null,
    removeItem: (key: string) => entries.delete(key),
  })
  return entries
}

afterEach(() => {
  vi.resetAllMocks()
  vi.unstubAllGlobals()
})

describe('legacy model migration', () => {
  it('keeps the legacy entry when the server fails to save', async () => {
    const entries = setup()
    vi.mocked(api.modelPreference).mockResolvedValue(null)
    vi.mocked(api.activateModel).mockRejectedValue(new Error('save failed'))
    await expect(migrateLegacyModel('owner', () => true)).rejects.toThrow('save failed')
    expect(entries.get(storageKey)).toBe(JSON.stringify(legacy))
  })

  it('clears the entry after a successful encrypted save', async () => {
    const entries = setup()
    const publicConfig = { provider: 'deepseek', model: 'demo', base_url: '', has_api_key: true } as const
    vi.mocked(api.modelPreference).mockResolvedValue(null)
    vi.mocked(api.activateModel).mockResolvedValue(publicConfig)
    await migrateLegacyModel('owner', () => true)
    expect(api.activateModel).toHaveBeenCalledWith({ ...legacy, base_url: '', migration_user_id: 'owner' })
    expect(entries.has(storageKey)).toBe(false)
  })

  it('keeps the existing server configuration', async () => {
    const entries = setup()
    vi.mocked(api.modelPreference).mockResolvedValue({
      provider: 'deepseek', model: 'existing', base_url: '', has_api_key: true,
    })
    await migrateLegacyModel('owner', () => true)
    expect(api.activateModel).not.toHaveBeenCalled()
    expect(entries.has(storageKey)).toBe(false)
  })
})
