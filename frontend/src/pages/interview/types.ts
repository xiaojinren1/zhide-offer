import type { ResumeProfile } from '../../lib/types'

export interface Snapshot { resume_profile: ResumeProfile; resume_markdown: string; jd_text: string; captured_at: string }
export interface Source { id: string; kind: 'resume' | 'jd'; label: string; text: string }
export interface BankQuestion {
  id: string; category: string; question: string; focus: string; source_ids: string[]
  follow_ups: string[]; answer_structure: string[]; sample_answer: string; missing: string[]
}
export interface Bank { id: string; job_title: string; questions: BankQuestion[]; sources: Source[]; snapshot: Snapshot }
export interface InterviewContext {
  job_title: string; sources: Source[]; resume_markdown: string; jd_text: string
  topics: { id: string; category: string; focus: string; source_ids: string[] }[]
}
export interface Turn {
  id: string; question: { text: string; stage: string; topic_id: string; is_follow_up: boolean; suggest_finish: boolean }
  answer: string | null; skipped: boolean
}
export interface Session {
  id: string; bank_id: string | null; version: number; status: 'active' | 'ended'; turns: Turn[]
  elapsed_seconds: number; job_title: string; started_at: string
  mode?: 'bank' | 'direct'; snapshot?: Snapshot
}
export interface Citation { turn_id: string; quote: string }
export interface Report {
  kind: 'complete' | 'partial'; overall_score: number | null; summary: string; hr_feedback: string; interviewer_feedback: string
  dimensions: { key: string; label: string; score: number | null; comment: string; evidence: Citation[] }[]
  strengths: { title: string; advice: string; evidence: Citation[] }[]
  improvements: { title: string; advice: string; evidence: Citation[] }[]
  optimized_answers: { turn_id: string; answer_excerpt: string; structure: string[]; example_answer: string; missing: string[] }[]
  recommendations: { topic_id: string; action: string }[]
  coverage: { topic_id: string; focus: string; asked: boolean; answered: boolean }[]
  disclaimer: string; answered_count: number
}
export interface ReportResponse { ok: true; session: Session; report: Report; saved: boolean; save_error: string | null; record_id: string | null }

export type Obj = Record<string, unknown>
export const object = (v: unknown): v is Obj => Boolean(v) && typeof v === 'object' && !Array.isArray(v)
const str = (v: unknown): v is string => typeof v === 'string'
const strings = (v: unknown): v is string[] => Array.isArray(v) && v.every(str)
const list = (v: unknown, check: (x: unknown) => boolean): boolean => Array.isArray(v) && v.every(check)
const fields = (v: Obj, keys: string[]) => keys.every((k) => str(v[k]))
const citation = (v: unknown) => object(v) && fields(v, ['turn_id', 'quote'])
const score = (v: unknown) => v === null || (typeof v === 'number' && Number.isFinite(v) && v >= 0 && v <= 100)
export function isSnapshot(v: unknown): v is Snapshot {
  return object(v) && fields(v, ['resume_markdown', 'jd_text', 'captured_at']) && object(v.resume_profile)
}
export function isContext(v: unknown): v is InterviewContext {
  return object(v) && fields(v, ['job_title', 'resume_markdown', 'jd_text'])
    && list(v.sources, (s) => object(s) && fields(s, ['id', 'label', 'text']) && ['resume', 'jd'].includes(String(s.kind)))
    && Array.isArray(v.topics) && v.topics.length > 0 && list(v.topics, (t) => object(t)
      && fields(t, ['id', 'category', 'focus']) && strings(t.source_ids))
}
export function isBank(v: unknown, historical = false): v is Bank {
  return object(v) && fields(v, ['id', 'job_title']) && isSnapshot(v.snapshot)
    && list(v.sources, (s) => object(s) && fields(s, ['id', 'label', 'text']) && ['resume', 'jd'].includes(String(s.kind)))
    && Array.isArray(v.questions) && v.questions.length >= (historical ? 1 : 10) && v.questions.length <= (historical ? 100 : 30)
    && (historical || new Set(v.questions.map((q) => object(q) && typeof q.question === 'string' ? q.question.replace(/[\p{P}\p{Z}\s_]+/gu, '').toLowerCase() : null)).size === v.questions.length)
    && list(v.questions, (q) => object(q)
      && fields(q, ['id', 'category', 'question', 'focus', 'sample_answer'])
      && ['source_ids', 'follow_ups', 'answer_structure', 'missing'].every((k) => strings(q[k])))
}
export function isTurn(v: unknown): v is Turn {
  return object(v) && str(v.id) && (v.answer === null || str(v.answer)) && typeof v.skipped === 'boolean'
    && object(v.question) && fields(v.question, ['text', 'stage', 'topic_id'])
    && typeof v.question.is_follow_up === 'boolean' && typeof v.question.suggest_finish === 'boolean'
}
export function isSession(v: unknown): v is Session {
  return object(v) && fields(v, ['id', 'job_title', 'started_at']) && (v.bank_id === null || str(v.bank_id))
    && (v.mode === undefined || ['bank', 'direct'].includes(String(v.mode)))
    && (v.snapshot === undefined || isSnapshot(v.snapshot)) && ['active', 'ended'].includes(String(v.status))
    && Number.isInteger(v.version) && typeof v.elapsed_seconds === 'number' && Number.isFinite(v.elapsed_seconds)
    && Array.isArray(v.turns) && v.turns.length > 0 && list(v.turns, isTurn)
}
export function isReport(v: unknown): v is Report {
  const finding = (f: unknown) => object(f) && fields(f, ['title', 'advice']) && list(f.evidence, citation)
  return object(v) && fields(v, ['summary', 'hr_feedback', 'interviewer_feedback', 'disclaimer'])
    && ['complete', 'partial'].includes(String(v.kind)) && score(v.overall_score) && typeof v.answered_count === 'number'
    && Array.isArray(v.dimensions) && v.dimensions.length === 5 && list(v.dimensions, (d) => object(d)
      && fields(d, ['key', 'label', 'comment']) && score(d.score) && list(d.evidence, citation))
    && list(v.strengths, finding) && list(v.improvements, finding)
    && list(v.optimized_answers, (a) => object(a) && fields(a, ['turn_id', 'answer_excerpt', 'example_answer']) && strings(a.structure) && strings(a.missing))
    && list(v.recommendations, (r) => object(r) && fields(r, ['topic_id', 'action']))
    && list(v.coverage, (c) => object(c) && fields(c, ['topic_id', 'focus']) && typeof c.asked === 'boolean' && typeof c.answered === 'boolean')
}
