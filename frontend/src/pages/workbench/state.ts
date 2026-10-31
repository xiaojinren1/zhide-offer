import axios from 'axios'
import type { ResumeProfile } from '../../lib/types'

export const FILE_ACCEPT = '.txt,.md,.docx,.pdf'
export const MAX_FILE_BYTES = 10 * 1024 * 1024

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
  if (!profile.experiences.length) return '尚无经历，请补充至少一段真实经历。'
  if (!profile.user_confirmed) return '请核对并勾选事实确认；修改岗位后也需重新确认。'
  if (!jdText.trim()) return '请在第 3 步填写目标岗位 JD。'
  return ''
}

export function progress(profile: ResumeProfile | null, jdText: string, markdown: string) {
  const blocked = generationBlock(profile, jdText)
  if (!profile) return { step: 1, label: '待整理' }
  if (!profile.experiences.length || !profile.user_confirmed) return { step: 2, label: '待确认' }
  if (!jdText.trim()) return { step: 3, label: '已确认 · 待填写岗位' }
  return { step: 4, label: markdown.trim() && !blocked ? '已生成' : '已确认 · 待生成' }
}

export function parsedProfile(result: { ok: boolean; error?: string; profile?: ResumeProfile }): ResumeProfile {
  if (!result.ok || !result.profile) throw new Error(result.error || '未收到解析结果，请检查材料后重试。')
  if (!Array.isArray(result.profile.experiences) || !result.profile.experiences.length) throw new Error('没有识别到经历。请补充项目、实习或工作内容；扫描 PDF 请先转为文字。')
  return { ...result.profile, user_confirmed: false }
}

export function generatedMarkdown(result: { ok: boolean; error?: string; markdown?: string }): string {
  if (!result.ok || !result.markdown?.trim()) throw new Error(result.error || '模型未返回简历正文，请重新生成。')
  return result.markdown
}

export function changedFacts(profile: ResumeProfile): ResumeProfile {
  return { ...profile, user_confirmed: false }
}
