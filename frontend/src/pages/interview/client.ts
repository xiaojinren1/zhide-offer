import { SESSION_EXPIRED_EVENT } from '../../lib/api'
import { isBank, isSession, isReport, object } from './types'
import type { Bank, Session, ReportResponse } from './types'

const messages: Record<number, string> = {
  401: '登录状态已失效，请重新登录。', 409: '面试或账户状态已变化，请核对后重试。',
  413: '材料过大，请缩减后重试。', 422: '提交内容不符合要求，请检查回答和材料后重试。',
  429: '模型服务繁忙或额度不足，请稍后重试。', 502: '模型返回格式无效，请重试。',
  503: '服务暂不可用，请检查配置后重试。', 504: '模型处理超时，请重试。',
}
export async function request(path: string, body: Record<string, unknown>, signal: AbortSignal): Promise<Record<string, unknown>> {
  const controller = new AbortController()
  const abort = () => controller.abort()
  signal.addEventListener('abort', abort, { once: true })
  if (signal.aborted) controller.abort()
  const timeout = setTimeout(abort, 180000)
  try {
    const response = await fetch('/api/interview/' + path, {
      method: 'POST', credentials: 'same-origin', signal: controller.signal,
      headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' }, body: JSON.stringify(body),
    })
    let data: unknown
    try { data = await response.json() } catch { throw new Error(messages[response.status] || '服务返回格式无效，请重试。') }
    if (signal.aborted) throw new Error('请求已取消')
    if (!response.ok) {
      if (response.status === 401) window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT))
      throw new Error(object(data) && typeof data.detail === 'string' ? data.detail : messages[response.status] || '请求失败，请重试。')
    }
    if (!object(data) || data.ok !== true) throw new Error('响应内容不完整，请重试。')
    return data
  } catch (e) {
    if (controller.signal.aborted && !signal.aborted) throw new Error('模型处理超时，已保留当前内容，请重试。')
    throw e
  } finally { clearTimeout(timeout); signal.removeEventListener('abort', abort) }
}
export const interviewClient = {
  start: async (body: Record<string, unknown>, signal: AbortSignal): Promise<Session> => {
    const data = await request('start', body, signal)
    if (!isSession(data.session)) throw new Error('对话内容不完整，请重试。')
    return data.session
  },
  bank: async (body: Record<string, unknown>, signal: AbortSignal): Promise<Bank> => {
    const data = await request('bank', body, signal)
    if (!isBank(data.bank)) throw new Error('题库内容不完整，请重试。')
    return data.bank
  },
  turn: async (body: Record<string, unknown>, signal: AbortSignal): Promise<Session> => {
    const data = await request('turn', body, signal)
    if (!isSession(data.session)) throw new Error('对话内容不完整，请重试。')
    return data.session
  },
  report: async (body: Record<string, unknown>, signal: AbortSignal): Promise<ReportResponse> => {
    const data = await request('report', body, signal)
    if (!isSession(data.session) || !isReport(data.report) || typeof data.saved !== 'boolean'
      || !(data.save_error === null || typeof data.save_error === 'string')) throw new Error('报告内容不完整，请重试。')
    return data as unknown as ReportResponse
  },
}
