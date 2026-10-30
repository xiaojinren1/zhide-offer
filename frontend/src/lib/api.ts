import axios from 'axios'
import type { InternalAxiosRequestConfig } from 'axios'
import type {
  MatchReport, ParsedJD, QualityReport, ResumeProfile, Suspicion,
} from './types'

export type AccountUser = { id: string; username: string }
export const SESSION_EXPIRED_EVENT = 'zhide:session-expired'
export const ACCOUNT_CHANGED_EVENT = 'zhide:account-changed'
let authGeneration = 0
type AccountRequestConfig = InternalAxiosRequestConfig & { accountGeneration?: number }
const accountChannel = typeof BroadcastChannel === 'undefined' ? null : new BroadcastChannel('zhide:account')
export function invalidateAuthRequests() { authGeneration += 1 }
accountChannel?.addEventListener('message', () => {
  invalidateAuthRequests()
  window.dispatchEvent(new Event(ACCOUNT_CHANGED_EVENT))
})
function announceAccountChange() {
  invalidateAuthRequests()
  accountChannel?.postMessage('changed')
}

const http = axios.create({
  baseURL: '/api', timeout: 180000, withCredentials: true,
  headers: { 'X-Requested-With': 'XMLHttpRequest' },
})
http.interceptors.request.use((config) => {
  const accountConfig = config as AccountRequestConfig
  accountConfig.accountGeneration = authGeneration
  return config
})
http.interceptors.response.use((response) => response, (error) => {
  if (error.response?.status === 401 && error.config?.accountGeneration === authGeneration && !error.config?.url?.startsWith('/auth/')) {
    window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT))
  }
  return Promise.reject(error)
})

export function apiErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const data = error.response?.data
    if (typeof data?.detail === 'string') return data.detail
    if (typeof data?.error === 'string') return data.error
    if (error.response?.status === 422) return '请检查用户名和密码是否符合要求。'
    if (!error.response) return '暂时无法连接服务，请检查服务状态后重试。'
  }
  return error instanceof Error ? error.message : '操作失败，请重试。'
}

export const api = {
  me: () => http.get('/auth/me').then((r) => r.data) as Promise<{ ok: true; user: AccountUser }>,
  login: (username: string, password: string) =>
    http.post('/auth/login', { username, password }).then((r) => { announceAccountChange(); return r.data }) as Promise<{ ok: true; user: AccountUser }>,
  register: (username: string, password: string) =>
    http.post('/auth/register', { username, password }).then((r) => { announceAccountChange(); return r.data }) as Promise<{ ok: true; user: AccountUser }>,
  logout: () => http.post('/auth/logout').then((r) => { announceAccountChange(); return r.data }) as Promise<{ ok: true }>,
  health: () => http.get('/health').then((r) => r.data),

  parseResumeFile: (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return http.post('/resume/parse', fd).then((r) => r.data) as Promise<{
      ok: boolean; error?: string; profile?: ResumeProfile; raw_text?: string
    }>
  },

  parseResumeText: (text: string) =>
    http.post('/resume/parse-text', { text }).then((r) => r.data) as Promise<{
      ok: boolean; error?: string; profile?: ResumeProfile; raw_text?: string
    }>,

  parseJd: (jd_text: string) =>
    http.post('/diagnose/parse-jd', { jd_text }).then((r) => r.data) as Promise<{
      ok: boolean; error?: string; jd?: ParsedJD
    }>,

  diagnose: (jd_text: string, resume_profile: ResumeProfile) =>
    http.post('/diagnose', { jd_text, resume_profile }).then((r) => r.data) as Promise<{
      ok: boolean; error?: string; jd?: ParsedJD
    } & MatchReport & { missing_hard_count?: number }>,

  generateResume: (jd_text: string, resume_profile: ResumeProfile, jd_keywords: string[] = []) =>
    http.post('/resume/generate', { jd_text, resume_profile, jd_keywords }).then((r) => r.data) as Promise<{
      ok: boolean; error?: string; markdown?: string
      untraceable?: string[]; traceability_passed?: boolean
      slimming?: { total: number; used: number; dropped: string[] }
    }>,

  quality: (jd_text: string, resume_profile: ResumeProfile, resume_markdown: string, jd_keywords: string[] = []) =>
    http.post('/quality', { jd_text, resume_profile, resume_markdown, jd_keywords }).then((r) => r.data) as Promise<{
      ok: boolean; error?: string
    } & QualityReport>,

  interview: (resume_markdown: string, resume_profile: ResumeProfile, jd_text = '') =>
    http.post('/interview', { resume_markdown, resume_profile, jd_text }).then((r) => r.data) as Promise<{
      ok: boolean; error?: string; questions?: Array<{
        question: string; trap: string; answer_key: string; source_suspicion: string
      }>; suspicions?: Suspicion[]
    }>,

  // 长期记忆：经历库持久化
  saveProfile: (name: string, profile: ResumeProfile) =>
    http.post('/profiles/save', { name, profile }).then((r) => r.data) as Promise<{
      ok: boolean; error?: string; id?: string; saved_at?: string
    }>,
  listProfiles: () =>
    http.get('/profiles/list').then((r) => r.data) as Promise<{
      ok: boolean; error?: string
      profiles?: Array<{ id: string; name: string; saved_at: string; experience_count: number }>
    }>,
  loadProfile: (id: string) =>
    http.get(`/profiles/${id}`).then((r) => r.data) as Promise<{
      ok: boolean; error?: string; profile?: ResumeProfile
      meta?: { id: string; name: string; saved_at: string }
    }>,
  deleteProfile: (id: string) =>
    http.delete(`/profiles/${id}`).then((r) => r.data) as Promise<{ ok: boolean; error?: string }>,
}
