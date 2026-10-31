import type { MatchReport } from '../../lib/types'

const invalid = () => new Error('匹配结果格式不完整或无效，请重试诊断；若仍失败，请检查服务端返回。')
const object = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

function optionalText(value: unknown): string {
  if (value === undefined) return ''
  if (typeof value !== 'string') throw invalid()
  return value.trim()
}

function textList(value: unknown): string[] {
  if (!Array.isArray(value) || value.some(item => typeof item !== 'string' || !item.trim())) throw invalid()
  return value.map(item => item.trim())
}

export interface ValidatedDiagnosis extends MatchReport {
  ok: true
  keywords: string[]
  missing_hard_count: number
}

// The transport type is not a runtime guarantee. Reject the whole report before rendering.
export function validateDiagnosis(value: unknown): ValidatedDiagnosis {
  if (!object(value)) throw invalid()
  if (value.ok !== true) {
    throw new Error(typeof value.error === 'string' && value.error.trim() ? value.error : '诊断失败，请重试。')
  }
  if (typeof value.coverage !== 'number' || !Number.isFinite(value.coverage) || value.coverage < 0 || value.coverage > 1) throw invalid()
  if (!Array.isArray(value.items) || !value.items.length) throw invalid()
  const items = value.items.map<MatchReport['items'][number]>(item => {
    if (!object(item) || typeof item.requirement !== 'string' || !item.requirement.trim()) throw invalid()
    const status = item.status
    if (status !== 'covered' && status !== 'partial' && status !== 'missing') throw invalid()
    const evidence = optionalText(item.evidence)
    if (status !== 'missing' && !evidence) throw invalid()
    return { requirement: item.requirement.trim(), status, evidence, note: optionalText(item.note) }
  })
  const missing_hard = textList(value.missing_hard)
  if (value.missing_hard_count !== undefined &&
    (!Number.isSafeInteger(value.missing_hard_count) || value.missing_hard_count !== missing_hard.length)) throw invalid()
  let keywords: string[] = []
  if (value.jd !== undefined) {
    if (!object(value.jd)) throw invalid()
    if (value.jd.keywords !== undefined) keywords = textList(value.jd.keywords)
  }
  return { ok: true, job_title: optionalText(value.job_title), coverage: value.coverage,
    items, missing_hard, missing_hard_count: missing_hard.length, keywords }
}
