import axios, { AxiosError } from 'axios'
import { describe, expect, it, vi } from 'vitest'

vi.stubGlobal('BroadcastChannel', undefined)
const requestAdapter = vi.fn()
const previousAdapter = axios.defaults.adapter
axios.defaults.adapter = requestAdapter
const { api, apiErrorMessage, SESSION_EXPIRED_EVENT } = await import('./api')
axios.defaults.adapter = previousAdapter
const responseError = (status: number, data: unknown = {}) => ({ isAxiosError: true, response: { status, data } })

describe('统一接口错误提示', () => {
  it('优先展示服务端原始 detail 或 error', () => {
    expect(apiErrorMessage(responseError(504, { detail: '生成未在规定时间完成' }))).toBe('生成未在规定时间完成')
    expect(apiErrorMessage(responseError(422, { error: '请先确认经历' }))).toBe('请先确认经历')
  })
  it.each([401, 409, 413, 422, 429, 502, 503, 504])('HTTP %s没有文字详情时提供对应中文提示', (status) => {
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
  it('公共请求层保留错误对象和响应，并向旧页面提供中文 message', async () => {
    const dispatch = vi.fn()
    vi.stubGlobal('window', { dispatchEvent: dispatch })
    const upstreamFailure = new AxiosError('Request failed with status code 503', 'ERR_BAD_RESPONSE')
    requestAdapter.mockImplementationOnce(async (config) => {
      upstreamFailure.config = config
      upstreamFailure.response = { status: 503, statusText: 'Service Unavailable', headers: {}, config, data: { detail: '模型服务暂不可用，请稍后重试' } }
      throw upstreamFailure
    })
    try {
      await expect(api.parseResumeText('虚构材料')).rejects.toBe(upstreamFailure)
      expect(upstreamFailure.message).toBe('模型服务暂不可用，请稍后重试')
      expect(String(upstreamFailure)).toContain('模型服务暂不可用')
      expect(upstreamFailure.response?.status).toBe(503)
      expect(dispatch).not.toHaveBeenCalledWith(expect.objectContaining({ type: SESSION_EXPIRED_EVENT }))
    } finally {
      requestAdapter.mockReset()
      vi.unstubAllGlobals()
    }
  })
  it.each([401, 429, 502, 503, 504])('请求层HTTP %s仅在应用401时通知登录失效', async (status) => {
    const dispatch = vi.fn()
    vi.stubGlobal('window', { dispatchEvent: dispatch })
    requestAdapter.mockImplementationOnce(async (config) => {
      throw new AxiosError('Request failed', 'ERR_BAD_RESPONSE', config, undefined,
        { status, statusText: '', headers: {}, config, data: {} })
    })
    try {
      await expect(api.parseResumeText('虚构材料')).rejects.toThrow(/[\u4e00-\u9fff]/)
      expect(dispatch).toHaveBeenCalledTimes(status === 401 ? 1 : 0)
      if (status === 401) expect(dispatch).toHaveBeenCalledWith(expect.objectContaining({ type: SESSION_EXPIRED_EVENT }))
    } finally {
      requestAdapter.mockReset()
      vi.unstubAllGlobals()
    }
  })
})
