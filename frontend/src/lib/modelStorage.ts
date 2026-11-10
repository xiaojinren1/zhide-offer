import { api } from './api'
import type { TextModelPreference } from './api'

export const modelStorageKey = (userId: string) => `jobagent:text-model:${userId}`

export function readSavedModel(userId: string) {
  const saved = localStorage.getItem(modelStorageKey(userId))
  return saved ? JSON.parse(saved) as TextModelPreference & { api_key: string } : null
}

export async function restoreSavedModel(userId: string, isCurrent: () => boolean) {
  if (!window.isSecureContext) return
  const saved = readSavedModel(userId)
  if (saved && !(await api.modelPreference()) && isCurrent()) await api.activateModel(saved)
}
