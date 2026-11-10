import { api } from './api'
import type { TextModelPreference } from './api'

const modelStorageKey = (userId: string) => `jobagent:text-model:${userId}`

export function clearLegacyModel(userId: string) {
  localStorage.removeItem(modelStorageKey(userId))
}

export async function migrateLegacyModel(userId: string, isCurrent: () => boolean) {
  if (!window.isSecureContext) return
  const raw = localStorage.getItem(modelStorageKey(userId))
  if (!raw) return
  const current = await api.modelPreference()
  if (!isCurrent()) return
  if (!current) {
    const saved = JSON.parse(raw) as Pick<TextModelPreference, 'provider' | 'model'> & {
      base_url?: string
      api_key: string
    }
    await api.activateModel({
      provider: saved.provider, model: saved.model, base_url: saved.base_url ?? '',
      api_key: saved.api_key, migration_user_id: userId,
    })
  }
  if (localStorage.getItem(modelStorageKey(userId)) === raw) clearLegacyModel(userId)
}
