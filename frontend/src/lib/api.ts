import axios from 'axios'
import type { InternalAxiosRequestConfig } from 'axios'
import type {
  InterviewQuestion, InterviewScore, MatchReport, ParsedJD, QualityReport, ResumeProfile, Suspicion,
} from './types'
import type { InterviewRecord, InterviewRecordInput, WorkspaceResponse, WorkspaceState } from './workspace'
import type { TailoringReport } from './tailoring'
import type { ResumeAppearance } from '../pages/workbench/ResumePreview'

type ResumeShare = { token: string; published_at: string }

export type AccountUser = { id: string; username: string; avatar_url?: string | null; guest?: boolean }
export const MODEL_CONFIGURATION_REQUIRED_EVENT = 'zhide:model-configuration-required'
export function notifyModelConfigurationRequired(message: string) {
  window.dispatchEvent(new CustomEvent(MODEL_CONFIGURATION_REQUIRED_EVENT, { detail: message }))
}

export const SESSION_EXPIRED_EVENT = 'zhide:session-expired'
export const ACCOUNT_CHANGED_EVENT = 'zhide:account-changed'
export const PROFILE_UPDATED_EVENT = 'zhide:profile-updated'
let authGeneration = 0
type AccountRequestConfig = InternalAxiosRequestConfig & { accountGeneration?: number }
const accountChannel = typeof BroadcastChannel === 'undefined' ? null : new BroadcastChannel('zhide:account')
export function invalidateAuthRequests() { authGeneration += 1 }
accountChannel?.addEventListener('message', (event: MessageEvent) => {
  if (event.data?.type === 'profile-updated') {
    window.dispatchEvent(new Event(PROFILE_UPDATED_EVENT))
    return
  }
  invalidateAuthRequests()
  window.dispatchEvent(new Event(ACCOUNT_CHANGED_EVENT))
})
function announceAccountChange() {
  invalidateAuthRequests()
  accountChannel?.postMessage('changed')
}
function announceProfileUpdate() {
  accountChannel?.postMessage({ type: 'profile-updated' })
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
  if (axios.isAxiosError(error)) {
    error.message = apiErrorMessage(error)
    if (error.response?.status === 428 && (error.config as AccountRequestConfig | undefined)?.accountGeneration === authGeneration) {
      notifyModelConfigurationRequired(error.message)
    }
  }
  return Promise.reject(error)
})

export function apiErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const data = error.response?.data
    if (typeof data?.detail === 'string') return data.detail
    if (typeof data?.error === 'string') return data.error
    const messages: Record<number, string> = {
      401: '登录状态已失效，请重新登录。',
      409: '内容或账户状态已变化，请核对后重试。',
      413: '提交内容过大，请缩减材料后重试。',
      422: '提交内容不符合要求，请检查后重试。',
      429: '请求过于频繁或服务额度不足，请稍后重试。',
      502: '模型返回的内容为空或格式不正确，请重试。',
      503: '服务暂不可用，请检查服务配置后重试。',
      504: '处理超时，请稍后重试。',
    }
    if (error.response && messages[error.response.status]) return messages[error.response.status]
    if (!error.response) return '暂时无法连接服务，请检查服务状态后重试。'
  }
  return error instanceof Error ? error.message : '操作失败，请重试。'
}

export type ModelKind = 'text' | 'vision'
export type TextModelPreference = { provider: 'deepseek' | 'glm' | 'custom'; model: string; base_url: string; has_api_key: boolean }
type ModelConnection = Pick<TextModelPreference, "provider" | "base_url"> & { api_key: string }

type TokenCounts = { input_tokens: number | null; output_tokens: number | null; total_tokens: number | null }
type ModelUsageReport = {
  models: Array<TokenCounts & { model: string; calls: number; unknown_calls: number }>
  records: Array<TokenCounts & { id: number; model: string; used_at: string }>
  next_before: number | null
}

export type FeedbackStatus = 'pending' | 'reviewing' | 'resolved'
type FeedbackItem = { id: number; message: string; status: FeedbackStatus; created_at: string; username: string }

export const api = {
  currentResumeShare: () => http.get<ResumeShare | null>('/resume-share').then(r => r.data),
  publishResume: (expected_user_id: string, markdown: string, appearance: ResumeAppearance) =>
    http.post<ResumeShare>('/resume-share', { expected_user_id, markdown, appearance }).then(r => r.data),
  revokeResume: (expected_user_id: string) => http.post('/resume-share/revoke', { expected_user_id }),
  sharedResume: (token: string) =>
    http.get<{ markdown: string; appearance: ResumeAppearance }>(`/shared-resumes/${encodeURIComponent(token)}`).then(r => r.data),
  contact: () => http.get<{ qq: string | null }>('/contact').then(r => r.data),
  updateContact: (qq: string) => http.put('/user-stats/contact', { qq }),
  listFeedback: (manage: boolean, before?: number) =>
    http.get<{ can_manage: boolean; items: FeedbackItem[]; next_before: number | null }>(
      '/feedback', { params: { manage, before } },
    ).then((r) => r.data),
  submitFeedback: (message: string) => http.post('/feedback', { message }),
  updateFeedback: (id: number, status: FeedbackStatus) => http.patch(`/feedback/${id}`, { status }),
  modelUsage: (params: { before?: number; start?: string; end?: string }) =>
    http.get<ModelUsageReport>('/auth/model-usage', { params }).then((r) => r.data),
  startTrial: () => http.post("/auth/trial").then(() => announceAccountChange()),
  heartbeat: () => http.post('/user-stats/heartbeat'),
  interviewRelatedCards: (params: { jd_text?: string; company?: string; role?: string; limit?: number }) =>
    http.get('/interview/related-cards', { params }).then(r => r.data) as Promise<{
      ok: boolean
      items: Array<{
        id: string
        kind: string
        company: string
        role: string
        round: string
        title: string
        author: string
        helpful_count: number
        excerpt: string
      }>
      note: string
    }>,
  userStats: () => http.get<{
    online: number; registered: number; new_this_week: number
    trend: Array<{ date: string; registrations: number; tokens: number }>
  } | null>('/user-stats').then(r => r.data),
  errorTrend: (params: { days?: number; limit?: number } = {}) =>
    http.get('/user-stats/errors', { params }).then(r => r.data) as Promise<{
      ok: boolean
      window_days: number
      events_scanned: number
      totals: { '24h': number; window: number }
      retries: { '24h': number; window: number }
      by_category: Array<{ id: string; label: string; hint: string; last24h: number; window: number }>
      by_feature: Array<{ feature: string; last24h: number; window: number }>
      daily: Array<{ date: string; errors: number }>
      samples: Array<{ time: string; feature: string; category: string; category_label: string; trace_id: string }>
      recent: Array<{
        time: string
        first_time: string
        feature: string
        category: string
        category_label: string
        trace_id: string
        count: number
      }>
    }>,
  listAdmins: () => http.get<{ admins: string[] }>('/user-stats/admins').then(r => r.data),
  changeAdmin: (username: string, admin: boolean) => http.put('/user-stats/admins', { username, admin }),
  modelPreference: (kind: ModelKind = 'text') => http.get<TextModelPreference | null>('/model-preferences', { params: { kind } }).then(r => r.data),
  listModels: (config: ModelConnection, kind: ModelKind = 'text') =>
    http.post<{ models: string[] }>('/model-preferences/models', config, { params: { kind } }).then(r => r.data),
  activateModel: (config: ModelConnection & { model: string; migration_user_id?: string }, kind: ModelKind = 'text') =>
    http.post<TextModelPreference>('/model-preferences', config, { params: { kind } }).then(r => r.data),
  revealModelKey: (kind: ModelKind = 'text') => http.post<{ api_key: string }>('/model-preferences/reveal', undefined, { params: { kind } }).then(r => r.data),
  resetModel: (kind: ModelKind = 'text') => http.delete('/model-preferences', { params: { kind } }),
  me: () => http.get('/auth/me').then((r) => r.data) as Promise<{ ok: true; user: AccountUser }>,
  profile: () => http.get('/auth/profile').then((r) => r.data) as Promise<{ ok: true; user: AccountUser & { avatar_url: string | null } }>,
  changePassword: (current_password: string, new_password: string) =>
    http.post('/auth/change-password', { current_password, new_password }).then((r) => { announceAccountChange(); return r.data }) as Promise<{ ok: true; user: AccountUser }>,
  uploadAvatar: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return http.post('/auth/avatar', form).then((r) => { announceProfileUpdate(); return r.data }) as Promise<{ ok: true }>
  },
  removeAvatar: () =>
    http.delete('/auth/avatar').then((r) => { announceProfileUpdate(); return r.data }) as Promise<{ ok: true }>,
  login: (username: string, password: string) =>
    http.post('/auth/login', { username, password }).then((r) => { announceAccountChange(); return r.data }) as Promise<{ ok: true; user: AccountUser }>,
  register: (username: string, password: string) =>
    http.post('/auth/register', { username, password }).then((r) => { announceAccountChange(); return r.data }) as Promise<{ ok: true; user: AccountUser; recovery_code: string }>,
  resetPassword: (username: string, recovery_code: string, new_password: string) =>
    http.post('/auth/reset-password', { username, recovery_code, new_password }).then((r) => { announceAccountChange(); return r.data }) as Promise<{ ok: true; user: AccountUser }>,
  logout: () => http.post('/auth/logout').then((r) => { announceAccountChange(); return r.data }) as Promise<{ ok: true }>,
  health: () => http.get('/health').then((r) => r.data),
  loadWorkspace: () => http.get('/workspace').then((r) => r.data) as Promise<WorkspaceResponse>,
  saveWorkspace: (expected_user_id: string, revision: number, state: WorkspaceState) =>
    http.post('/workspace', { expected_user_id, revision, state }).then((r) => r.data) as Promise<{ ok: true; revision: number; saved_at: string }>,
  saveInterviewRecord: (expected_user_id: string, record: InterviewRecordInput) =>
    http.post('/interview-records', { ...record, expected_user_id }).then((r) => r.data) as Promise<{ ok: true; id: string; saved_at: string }>,
  listInterviewRecords: () => http.get('/interview-records').then((r) => r.data) as Promise<{ ok: true; records: Pick<InterviewRecord, 'id' | 'title' | 'saved_at'>[] }>,
  loadInterviewRecord: (id: string) => http.get(`/interview-records/${encodeURIComponent(id)}`).then((r) => r.data) as Promise<{ ok: true; record: InterviewRecord }>,
  deleteInterviewRecord: (id: string) => http.delete(`/interview-records/${encodeURIComponent(id)}`).then((r) => r.data) as Promise<{ ok: true }>,

  parseResumeFile: (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return http.post('/resume/parse', fd).then((r) => r.data) as Promise<{
      ok: boolean; error?: string; profile?: ResumeProfile; raw_text?: string
    }>
  },

  parseResumeImage: (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return http.post('/resume/parse-image', fd).then((r) => r.data) as Promise<{
      ok: boolean; error?: string; profile?: ResumeProfile; raw_text?: string
    }>
  },

  resumeTemplates: () =>
    http.get('/resume/templates').then(r => r.data) as Promise<{
      ok: boolean
      items: Array<{
        id: string
        name: string
        tags: string[]
        description: string
        appearance: Record<string, unknown>
      }>
      note?: string
    }>,

  recognizeResumeTemplate: (file: File, visual: boolean) => {
    const form = new FormData()
    form.append('file', file)
    return http.post<ResumeAppearance>(visual ? '/resume/template-image' : '/resume/template-document', form).then(r => r.data)
  },

  parseResumeText: (text: string) =>
    http.post('/resume/parse-text', { text }).then((r) => r.data) as Promise<{
      ok: boolean; error?: string; profile?: ResumeProfile; raw_text?: string
    }>,

  generateRole: (job_title: string) =>
    http.post('/diagnose/generate-role', { job_title }).then((r) => r.data) as Promise<{
      ok: boolean; error?: string; job_title?: string; jd_text?: string
    }>,

  parseJd: (jd_text: string) =>
    http.post('/diagnose/parse-jd', { jd_text }).then((r) => r.data) as Promise<{
      ok: boolean; error?: string; jd?: ParsedJD
    }>,

  diagnose: (jd_text: string, resume_profile: ResumeProfile, resume_markdown: string) =>
    http.post('/diagnose', { jd_text, resume_profile, resume_markdown }).then((r) => r.data) as Promise<{
      ok: boolean; error?: string; jd?: ParsedJD
    } & MatchReport & { missing_hard_count?: number }>,

  generateResume: (jd_text: string, resume_profile: ResumeProfile, jd_keywords: string[] = []) =>
    http.post('/resume/generate', { jd_text, resume_profile, jd_keywords }).then((r) => r.data) as Promise<{
      ok: boolean; error?: string; markdown?: string
      generation_mode?: 'initial' | 'tailored'
      untraceable?: string[]; traceability_passed?: boolean
      tailoring?: TailoringReport | null
      slimming?: { total: number; used: number; dropped: string[] }
    }>,
  reviseResume: (jd_text: string, resume_profile: ResumeProfile, resume_markdown: string, suggestions: Array<{ id: string; type: string; location: string; detail: string; suggestion: string; severity: string }>) =>
    http.post('/resume/revise', { jd_text, resume_profile, resume_markdown, suggestions }).then((r) => r.data) as Promise<{
      ok: boolean; error?: string; markdown?: string; untraceable?: string[]
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
  scoreInterview: (resume_profile: ResumeProfile | null, jd_text: string, question: InterviewQuestion, answer: string) =>
    http.post('/interview/score', { resume_profile, jd_text, question, answer }).then((r) => r.data) as Promise<InterviewScore & { ok?: boolean; detail?: string }>,

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
    http.get(`/profiles/${encodeURIComponent(id)}`).then((r) => r.data) as Promise<{
      ok: boolean; error?: string; profile?: ResumeProfile
      meta?: { id: string; name: string; saved_at: string; revision?: string }
    }>,
  updateProfile: (id: string, name: string, expected_revision: string, profile?: ResumeProfile) =>
    http.patch(`/profiles/${encodeURIComponent(id)}`, { name, expected_revision, profile }).then((r) => r.data) as Promise<{
      ok: boolean; error?: string; profile?: ResumeProfile
      meta?: { id: string; name: string; saved_at: string; revision?: string }
    }>,
  deleteProfile: (id: string) =>
    http.delete(`/profiles/${encodeURIComponent(id)}`).then((r) => r.data) as Promise<{ ok: boolean; error?: string }>,
}

// Uses the same account-generation and CSRF protections as the workbench.
export const libraryApi = {
  list: () => http.get('/library').then(r => r.data) as Promise<import('./library').Bank>,
  preview: (material: import('./library').Material) => http.post('/library/preview', material).then(r => r.data) as Promise<import('./library').Preview>,
  apply: (material: import('./library').Material, revision: number, choices: import('./library').Choice[]) => http.post('/library/import', {...material, revision, choices, facts_confirmed: true}).then(r => r.data) as Promise<{changed: number}>,
  action: (id: string, expected_user_id: string, revision: number, action: 'delete' | 'restore' | 'revert', version?: number) => http.post('/library/'+encodeURIComponent(id)+'/action', {expected_user_id,revision,action,version}).then(r => r.data),
}

// 岗位收件箱：文档列表 / 详情 / 导入 / 删除。权限由服务端按账户裁决。
export type JobDocument = {
  id: string
  kind: string
  source: string
  title: string
  company: string
  role: string
  city: string
  salary_text: string
  salary_min: number | null
  salary_max: number | null
  experience: string
  education: string
  url: string
  content_md: string
  structured: Record<string, unknown>
  visibility: string
  published_at: number | null
  updated_at: number
  matched_excerpt?: string
}

export type JobImportPayload = {
  text: string
  title?: string
  company?: string
  city?: string
  salary?: string
  url?: string
  source?: 'paste' | 'image' | 'manual' | 'upload' | 'feed'
  parse?: boolean
}

export const jobsApi = {
  list: (params: { kind?: string; q?: string; limit?: number; offset?: number; mine?: boolean } = {}) =>
    http.get('/jobs', { params }).then(r => r.data) as Promise<{
      ok: boolean; items: JobDocument[]; total: number; query: string | null
    }>,
  detail: (id: string) =>
    http.get(`/jobs/${encodeURIComponent(id)}`).then(r => r.data) as Promise<{
      ok: boolean; document: JobDocument; chunks: Array<{ index: number; text: string }>
    }>,
  import: (payload: JobImportPayload) =>
    http.post('/jobs/import', payload).then(r => r.data) as Promise<{
      ok: boolean; id: string; created: boolean; warnings: string[]; document: JobDocument
    }>,
  remove: (id: string) =>
    http.delete(`/jobs/${encodeURIComponent(id)}`).then(r => r.data) as Promise<{ ok: boolean }>,
  // 截图导入第一步：只把图片读成文字，不入库；用户核对后走 import 保存
  parseImage: (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return http.post('/jobs/parse-image', fd).then(r => r.data) as Promise<{
      ok: boolean
      error?: string
      text?: string
      guess?: PasteGuess
      warnings?: string[]
    }>
  },
}

export type ApplicationStage = 'saved' | 'tailored' | 'applied' | 'interview' | 'offer' | 'rejected' | 'archived'

export type JobApplication = {
  id: string
  doc_id: string
  stage: ApplicationStage
  stage_label: string
  next_stage: ApplicationStage[]
  next_action_at: number | null
  next_action_date: string
  note: string
  created_at: number
  updated_at: number
  job: { title: string; company: string; city: string; url: string; salary_text: string } | null
  history?: Array<{ from_stage: string; to_stage: string; note: string; created_at: number }>
}

export const applicationsApi = {
  list: (params: { stage?: string; include_archived?: boolean } = {}) =>
    http.get('/jobs/applications', { params }).then(r => r.data) as Promise<{
      ok: boolean
      items: JobApplication[]
      counts: Record<string, number>
      stages: Array<{ id: ApplicationStage; label: string }>
    }>,
  detail: (docId: string) =>
    http.get(`/jobs/applications/${encodeURIComponent(docId)}`).then(r => r.data) as Promise<{
      ok: boolean
      application: JobApplication
    }>,
  advance: (docId: string, payload: { stage: ApplicationStage; note?: string; next_action?: string }) =>
    http.post(`/jobs/applications/${encodeURIComponent(docId)}`, payload).then(r => r.data) as Promise<{
      ok: boolean
      application: JobApplication
    }>,
  remove: (docId: string) =>
    http.delete(`/jobs/applications/${encodeURIComponent(docId)}`).then(r => r.data) as Promise<{ ok: boolean }>,
}

export type JobPipelineResult = {
  ok: boolean
  stage?: string
  error?: string
  doc_id?: string
  title?: string
  jd?: { keywords?: string[] } | null
  match?: {
    coverage?: number | null
    missing_hard_count?: number | null
    items?: Array<{ requirement?: string; status?: string; suggestion?: string }>
  }
  markdown?: string
  keyword_coverage?: number | null
  quality?: {
    passed?: boolean | null
    failure_reasons?: string[]
    issues?: Array<{ type?: string; detail?: string; suggestion?: string }>
  }
}

export const jobsPipelineApi = {
  run: (docId: string, payload: { resume_profile: Record<string, unknown>; resume_markdown?: string }) =>
    http.post(`/jobs/${encodeURIComponent(docId)}/pipeline`, payload).then(r => r.data) as Promise<JobPipelineResult>,
}

export type JobSource = {
  id: string
  name: string
  kind: string
  url: string
  tier: number
  enabled: number
  license_note: string
  last_run_at: number | null
  last_status: string
}

export type JobSourceInput = {
  id: string
  name: string
  kind: 'rss' | 'html_list'
  url: string
  tier: number
  license_note: string
  config: Record<string, unknown>
}

export const jobsSourceApi = {
  list: () => http.get('/jobs/sources').then(r => r.data) as Promise<{ ok: boolean; items: JobSource[] }>,
  save: (payload: JobSourceInput) =>
    http.post('/jobs/sources', payload).then(r => r.data) as Promise<{ ok: boolean; source: string }>,
  fetch: (id: string) =>
    http.post(`/jobs/sources/${encodeURIComponent(id)}/fetch`).then(r => r.data) as Promise<{
      ok: boolean; source: string; items?: number; created?: number; updated?: number
      skipped?: number; seconds?: number; error?: string; status?: string
    }>,
}

export type JobProvince = {
  code: string
  name: string
  url: string
  verified: boolean
  note?: string
  source_id: string
  enabled: boolean
  current_url: string
  last_run_at: number | null
  last_status: string
}

export const jobsProvinceApi = {
  list: () => http.get('/jobs/provinces').then(r => r.data) as Promise<{ ok: boolean; items: JobProvince[] }>,
  enable: (code: string, url = '') =>
    http.post(`/jobs/provinces/${encodeURIComponent(code)}/enable`, { url }).then(r => r.data) as Promise<{
      ok: boolean; source_id: string; url: string; name: string
    }>,
  disable: (code: string) =>
    http.post(`/jobs/provinces/${encodeURIComponent(code)}/disable`).then(r => r.data) as Promise<{ ok: boolean }>,
}

export const jobsFetchAllApi = {
  all: () => http.post('/jobs/sources/fetch-all').then(r => r.data) as Promise<{
    ok: boolean; sources: number; remaining: number; failed: number
    created: number; updated: number; skipped: number
    items: Array<{ source: string; ok: boolean; created: number; updated: number; skipped: number; error: string }>
  }>,
}

export type PasteGuess = {
  title: string
  company: string
  city: string
  salary_text: string
  salary_min: number | null
  salary_max: number | null
  experience: string
  education: string
  url: string
  warnings: string[]
}

export const jobsPasteApi = {
  analyze: (text: string) =>
    http.post('/jobs/analyze', { text }).then(r => r.data) as Promise<{
      ok: boolean
      guess: PasteGuess
      duplicate: { id: string; title: string } | null
    }>,
}

export type CommunityCard = {
  id: string
  kind: 'interview' | 'referral' | 'jd_review'
  company: string
  role: string
  round: string
  title: string
  body_md: string
  tags: string[]
  status: 'pending' | 'public' | 'rejected'
  author: string
  helpful_count: number
  viewer_helpful: boolean
  comment_count: number
  report_count: number
  review_note: string
  revision: number
  created_at: number
  published_at: number | null
}

export type CommunityComment = {
  id: string
  card_id: string
  body: string
  author: string
  status: 'public' | 'rejected'
  report_count: number
  revision: number
  /** 卡片内容改版后，旧版本的评论 */
  outdated: boolean
  created_at: number
  mine: boolean
  can_manage: boolean
}

export type CommunityRevisionMeta = {
  revision: number
  title: string
  company: string
  role: string
  round: string
  tags: string[]
  created_at: number
}

export type CommunityRevision = CommunityRevisionMeta & { body_md: string }

export type CommunityReportGroup = {
  card_id: string
  title: string
  kind: CommunityCard['kind']
  company: string
  role: string
  round: string
  card_status: CommunityCard['status']
  report_count: number
  reasons: Array<{ reason: string; created_at: number }>
}

export type CommunitySubmitPayload = {
  kind: CommunityCard['kind']
  title: string
  body_md: string
  company?: string
  role?: string
  round?: string
  tags?: string[]
  doc_id?: string
}

export const communityApi = {
  list: (params: { kind?: string; company?: string; q?: string; before?: number; limit?: number } = {}) =>
    http.get('/community/cards', { params }).then(r => r.data) as Promise<{
      ok: boolean
      items: CommunityCard[]
      next_before: number | null
    }>,
  detail: (id: string) =>
    http.get(`/community/cards/${encodeURIComponent(id)}`).then(r => r.data) as Promise<{
      ok: boolean
      card: CommunityCard
    }>,
  mine: () =>
    http.get('/community/mine').then(r => r.data) as Promise<{ ok: boolean; items: CommunityCard[] }>,
  submit: (payload: CommunitySubmitPayload) =>
    http.post('/community/cards', payload).then(r => r.data) as Promise<{
      ok: boolean
      id: string
      status: string
      message: string
    }>,
  helpful: (id: string) =>
    http.post(`/community/cards/${encodeURIComponent(id)}/helpful`).then(r => r.data) as Promise<{
      ok: boolean
      helpful: boolean
      helpful_count: number
    }>,
  report: (id: string, reason: string) =>
    http.post(`/community/cards/${encodeURIComponent(id)}/report`, { reason }).then(r => r.data) as Promise<{
      ok: boolean
      report_count: number
      already: boolean
      hidden: boolean
      message: string
    }>,
  remove: (id: string) =>
    http.delete(`/community/cards/${encodeURIComponent(id)}`).then(r => r.data) as Promise<{ ok: boolean }>,
  reviewQueue: (params: { status?: string; before?: number } = {}) =>
    http.get('/community/review', { params }).then(r => r.data) as Promise<{
      ok: boolean
      items: CommunityCard[]
      counts: Record<string, number>
    }>,
  reviewCard: (id: string, action: 'approve' | 'reject' | 'unpublish', note: string) =>
    http.patch(`/community/cards/${encodeURIComponent(id)}`, { action, note }).then(r => r.data) as Promise<{
      ok: boolean
      status: string
      review_note: string
    }>,
  reports: (onlyOpen = true) =>
    http.get('/community/reports', { params: { only_open: onlyOpen } }).then(r => r.data) as Promise<{
      ok: boolean
      items: CommunityReportGroup[]
      sla: {
        open_cards: number
        oldest_open_hours: number
        over_24h: number
        handled_recent: number
        median_handle_hours: number
      }
    }>,
  resolveReports: (cardId: string, note = '') =>
    http.post(`/community/reports/${encodeURIComponent(cardId)}/resolve`, { note }).then(r => r.data) as Promise<{
      ok: boolean
      resolved: number
    }>,
  comments: (cardId: string) =>
    http.get(`/community/cards/${encodeURIComponent(cardId)}/comments`).then(r => r.data) as Promise<{
      ok: boolean
      items: CommunityComment[]
    }>,
  addComment: (cardId: string, body: string) =>
    http.post(`/community/cards/${encodeURIComponent(cardId)}/comments`, { body }).then(r => r.data) as Promise<{
      ok: boolean
      id: string
      status: string
      body: string
    }>,
  removeComment: (commentId: string) =>
    http.delete(`/community/comments/${encodeURIComponent(commentId)}`).then(r => r.data) as Promise<{ ok: boolean }>,
  reportComment: (commentId: string, reason: string) =>
    http.post(`/community/comments/${encodeURIComponent(commentId)}/report`, { reason }).then(r => r.data) as Promise<{
      ok: boolean
      report_count: number
      hidden: boolean
      message: string
    }>,
  commentQueue: () =>
    http.get('/community/comments/queue').then(r => r.data) as Promise<{
      ok: boolean
      items: CommunityComment[]
    }>,
  restoreComment: (commentId: string) =>
    http.post(`/community/comments/${encodeURIComponent(commentId)}/restore`).then(r => r.data) as Promise<{ ok: boolean }>,
  revise: (id: string, payload: { title?: string; body_md?: string; company?: string; role?: string; round?: string; tags?: string[] }) =>
    http.put(`/community/cards/${encodeURIComponent(id)}`, payload).then(r => r.data) as Promise<{
      ok: boolean
      status: string
      message: string
    }>,
  revisions: (id: string) =>
    http.get(`/community/cards/${encodeURIComponent(id)}/revisions`).then(r => r.data) as Promise<{
      ok: boolean
      items: CommunityRevisionMeta[]
      total: number
    }>,
  revision: (id: string, revision: number) =>
    http.get(`/community/cards/${encodeURIComponent(id)}/revisions/${revision}`).then(r => r.data) as Promise<{
      ok: boolean
      revision: CommunityRevision
    }>,
  resubmit: (id: string) =>
    http.post(`/community/cards/${encodeURIComponent(id)}/resubmit`).then(r => r.data) as Promise<{
      ok: boolean
      status: string
      message: string
    }>,
}
