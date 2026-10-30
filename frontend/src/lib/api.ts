import axios from 'axios'
import type {
  MatchReport, ParsedJD, QualityReport, ResumeProfile, Suspicion,
} from './types'

const http = axios.create({ baseURL: '/api', timeout: 180000 })

export const api = {
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
