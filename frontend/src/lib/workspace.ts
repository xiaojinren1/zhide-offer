import type { ResumeProfile } from './types'

export type WorkspacePage = 'workbench' | 'diagnose' | 'quality' | 'interview' | 'memory'
export interface WorkspaceState {
  source_text: string
  source_name: string
  jd_text: string
  profile: ResumeProfile | null
  jd_keywords: string[]
  markdown: string
  page: WorkspacePage
}
export const emptyWorkspace = (): WorkspaceState => ({
  source_text: '', source_name: '', jd_text: '', profile: null,
  jd_keywords: [], markdown: '', page: 'workbench',
})
export interface WorkspaceResponse {
  ok: true; revision: number; state: WorkspaceState | null; saved_at: string | null
}
export interface InterviewRecordInput {
  title: string
  jd_text?: string
  questions?: Record<string, unknown>[]
  answers?: string[]
  question_scores?: Record<string, unknown>[]
  overall_feedback?: Record<string, unknown>
}
export interface InterviewRecord extends InterviewRecordInput {
  id: string; saved_at: string
}

export function isWorkspaceState(value: unknown): value is WorkspaceState {
  if (!value || typeof value !== 'object') return false
  const state = value as Record<string, unknown>
  const strings = (items: unknown): items is string[] => Array.isArray(items) && items.every((item) => typeof item === 'string')
  if (!['source_text', 'source_name', 'jd_text', 'markdown'].every((key) => typeof state[key] === 'string') || !strings(state.jd_keywords)) return false
  if (!['workbench', 'diagnose', 'quality', 'interview', 'memory'].includes(String(state.page))) return false
  if (state.profile === null) return true
  if (!state.profile || typeof state.profile !== 'object') return false
  const profile = state.profile as Record<string, unknown>
  return typeof profile.name === 'string' && strings(profile.skills) && strings(profile.education)
    && (profile.user_confirmed === undefined || typeof profile.user_confirmed === 'boolean')
    && (profile.raw_text === undefined || typeof profile.raw_text === 'string')
    && Array.isArray(profile.experiences) && profile.experiences.every((item: unknown) => {
      if (!item || typeof item !== 'object') return false
      const experience = item as Record<string, unknown>
      return ['kind', 'name', 'role', 'period'].every((key) => typeof experience[key] === 'string')
        && ['actions', 'results', 'skills'].every((key) => strings(experience[key]))
    })
}
