import { describe, expect, it, vi } from 'vitest'

vi.stubGlobal('BroadcastChannel', undefined)
const { apiErrorMessage } = await import('./api')
const responseError = (status: number, data: unknown = {}) => ({ isAxiosError: true, response: { status, data } })

describe('统一接口错误提示', () => {
  it('优先展示服务端原始 detail 或 error', () => {
    expect(apiErrorMessage(responseError(504, { detail: '生成未在规定时间完成' }))).toBe('生成未在规定时间完成')
    expect(apiErrorMessage(responseError(422, { error: '请先确认经历' }))).toBe('请先确认经历')
  })
  it.each([401, 409, 413, 422, 429, 503, 504])('HTTP %s没有文字详情时提供对应中文提示', (status) => {
    const message = apiErrorMessage(responseError(status))
    expect(message).toMatch(/[\u4e00-\u9fff]/)
    expect(message).not.toContain('用户名和密码')
  })
  it('验证详情为数组时不直接转成用户看不懂的对象', () => {
    expect(apiErrorMessage(responseError(422, { detail: [{ type: 'missing' }] }))).toBe('提交内容不符合要求，请检查后重试。')
  })
  it('网络错误与未知异常保留明确提示', () => {
    expect(apiErrorMessage({ isAxiosError: true })).toContain('无法连接服务')
    expect(apiErrorMessage(new Error('本地检查失败'))).toBe('本地检查失败')
  })
})
