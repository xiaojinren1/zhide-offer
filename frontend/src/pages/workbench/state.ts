import axios from 'axios'
import type { Experience, ResumeProfile } from '../../lib/types'

export const FILE_ACCEPT = '.txt,.md,.docx,.pdf'
export const MAX_FILE_BYTES = 10 * 1024 * 1024

export function emptyExperience(): Experience {
  return { kind: 'project', name: '', role: '', period: '', actions: [], results: [], skills: [] }
}

export function manualProfile(sourceText: string): ResumeProfile {
  return { name: '', education: [], skills: [], experiences: [emptyExperience()], raw_text: sourceText, user_confirmed: false }
}

export function factIssues(profile: ResumeProfile): string[] {
  if (!profile.experiences.length) return ['尚无经历，请补充至少一段真实经历。']
  return profile.experiences.flatMap((experience, index) => {
    const issues: string[] = []
    if (!experience.name.trim()) issues.push(`第 ${index + 1} 段经历：请填写经历名称。`)
    if (experience.kind !== 'education' && ![...experience.actions, ...experience.results].some((line) => line.trim())) issues.push(`第 ${index + 1} 段经历：请至少填写一项行动或真实成果。`)
    return issues
  })
}

export function confirmedProfile(profile: ResumeProfile): ResumeProfile {
  const issues = factIssues(profile)
  if (issues.length) throw new Error(issues.join(' '))
  const clean = (items: string[]) => items.map((item) => item.trim()).filter(Boolean)
  return { ...profile, user_confirmed: true, skills: clean(profile.skills), education: clean(profile.education),
    experiences: profile.experiences.map((experience) => ({ ...experience, name: experience.name.trim(), role: experience.role.trim(), period: experience.period.trim(),
      actions: clean(experience.actions), results: clean(experience.results), skills: clean(experience.skills) })) }
}

export function fileError(file: Pick<File, 'name' | 'size'>): string {
  if (!/\.(txt|md|docx|pdf)$/i.test(file.name)) return '暂不支持此格式。请上传 TXT、Markdown、DOCX 或文字 PDF；图片、旧版 DOC 和扫描 PDF 的 OCR 尚未接入。'
  if (file.size === 0) return '文件为空，请选择包含文字的材料。'
  if (file.size > MAX_FILE_BYTES) return '文件超过 10 MB，请精简材料后重试。'
  return ''
}

export function operationError(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const status = error.response?.status
    const detail = error.response?.data?.detail || error.response?.data?.error
    if (error.code === 'ECONNABORTED' || error.code === 'ETIMEDOUT' || status === 504) return '处理超时，本次未完成。请稍后重试，或缩短材料与岗位描述。'
    if (status === 401) return '登录已失效，请重新登录后继续。'
    if (status === 429) return '请求过于频繁或额度不足，请稍后重试。'
    if (status === 503) return typeof detail === 'string' ? detail : '模型服务暂不可用，请联系负责人检查 API 配置。'
    if (typeof detail === 'string') return detail
    if (status === 422) return '输入内容不符合要求，请检查材料、事实确认状态和岗位 JD。'
    if (!error.response) return '暂时无法连接服务，请检查网络和本地后端，再重试。'
    return '服务处理失败，请稍后重试。'
  }
  return error instanceof Error ? error.message : '操作失败，请重试。'
}

export function generationBlock(profile: ResumeProfile | null, jdText: string): string {
  if (!profile) return '先整理材料，再核对事实。'
  const issues = factIssues(profile)
  if (issues.length) return issues[0]
  if (!profile.user_confirmed) return '请核对并勾选事实确认；修改岗位后也需重新确认。'
  if (!jdText.trim()) return '请在第 3 步填写目标岗位 JD。'
  return ''
}

export function progress(profile: ResumeProfile | null, jdText: string, markdown: string) {
  const blocked = generationBlock(profile, jdText)
  if (!profile) return { step: 1, label: '待整理' }
  if (factIssues(profile).length || !profile.user_confirmed) return { step: 2, label: '待确认' }
  if (!jdText.trim()) return { step: 3, label: '已确认 · 待填写岗位' }
  return { step: 4, label: markdown.trim() && !blocked ? '已生成' : '已确认 · 待生成' }
}

export function parsedProfile(result: { ok: boolean; error?: string; profile?: ResumeProfile }): ResumeProfile {
  if (!result.ok || !result.profile) throw new Error(result.error || '未收到解析结果，请检查材料后重试。')
  if (!Array.isArray(result.profile.experiences) || !result.profile.experiences.length) throw new Error('没有识别到经历。请补充项目、实习或工作内容；扫描 PDF 请先转为文字。')
  const strings = (value: unknown): value is string[] => Array.isArray(value) && value.every((item) => typeof item === 'string')
  const profile = result.profile
  if (typeof profile.name !== 'string' || !strings(profile.skills) || !strings(profile.education)
    || (profile.raw_text !== undefined && typeof profile.raw_text !== 'string')
    || !profile.experiences.every((experience) => experience && ['kind', 'name', 'role', 'period'].every((key) => typeof experience[key as keyof Experience] === 'string')
      && strings(experience.actions) && strings(experience.results) && strings(experience.skills))) {
    throw new Error('解析结果结构不完整，请重试整理或直接手工填写事实。')
  }
  return { ...result.profile, user_confirmed: false }
}

export function generatedMarkdown(result: { ok: boolean; error?: string; markdown?: string }): string {
  if (!result.ok || typeof result.markdown !== 'string' || !result.markdown.trim()) throw new Error(result.error || '模型未返回简历正文，请重新生成。')
  return result.markdown
}

export interface GenerationReview {
  title: string
  detail: string
  warning: boolean
}

// Local read-only view of existing response metadata; no shared API/storage changes.
export function generationReview(result: unknown): GenerationReview {
  const record = (value: unknown): Record<string, unknown> => value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
  const response = record(result)
  const check = record(response.self_check)
  const count = (value: unknown): value is number => typeof value === 'number' && Number.isSafeInteger(value) && value >= 0
  const issues = check.issues_remaining
  const high = check.high_remaining
  const countsValid = count(issues) && count(high) && high <= issues
  const notes: string[] = []
  const failed = check.passed === false || (count(high) && high > 0)
  if (failed) notes.push(countsValid ? `本稿质检未通过：剩余 ${issues} 项问题，其中高风险 ${high} 项。` : '本稿质检未通过，未收到完整的问题数量。')
  else if (countsValid && issues > 0) notes.push(`本稿仍有 ${issues} 项质检提示，其中高风险 ${high} 项。`)
  const numbersFailed = response.traceability_passed === false || (Array.isArray(response.untraceable) && response.untraceable.some((item) => typeof item === 'string' && item.trim()))
  if (numbersFailed) notes.push('数字追溯检查未通过，请核对材料依据；不要直接使用无依据的数字。')
  if (notes.length) return { title: failed ? '质检未通过 · 草稿待核对' : '草稿存在检查提示', detail: notes.join(' '), warning: true }
  if (check.passed !== true || !countsValid || response.traceability_passed !== true) return { title: '质检状态未知 · 草稿待核对', detail: '未收到与当前稿件对应的完整质检信息，可能是恢复的草稿或旧接口返回。请逐句核对后再使用。', warning: true }
  return { title: '自动检查完成 · 仍需事实核对', detail: '本轮自动检查未报告问题，但不代表事实已被认证；请逐句对照原始材料。', warning: false }
}

export function changedFacts(profile: ResumeProfile): ResumeProfile {
  return { ...profile, user_confirmed: false }
}
