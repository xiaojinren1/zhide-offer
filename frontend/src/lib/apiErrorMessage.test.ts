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

  it('面试记录 CRUD 使用账户预期值、编码记录 ID 并保留响应数据', async () => {
    const responses = [
      { ok: true, id: 'record-1', saved_at: '2026-10-31 12:00:00' },
      { ok: true, records: [{ id: 'record-1', title: '后端工程师 · 第一轮', saved_at: '2026-10-31 12:00:00' }] },
      { ok: true, record: { id: 'record/1', title: '后端工程师 · 第一轮', saved_at: '2026-10-31 12:00:00', questions: [], answers: [], question_scores: [], overall_feedback: {} } },
      { ok: true },
    ]
    const requests: Array<{ method?: string; url?: string; data?: unknown }> = []
    requestAdapter.mockImplementation(async (config) => {
      requests.push({ method: config.method, url: config.url, data: config.data ? JSON.parse(config.data) : undefined })
      const data = responses.shift()
      return { data, status: 200, statusText: 'OK', headers: {}, config }
    })
    try {
      await expect(api.saveInterviewRecord('user-a', {
        title: '后端工程师 · 第一轮',
        jd_text: '负责服务端开发',
        questions: [{ question: '请介绍项目' }],
        answers: ['虚构回答'],
        question_scores: [{ total: 80 }],
        overall_feedback: { next: '继续练习' },
      })).resolves.toEqual({ ok: true, id: 'record-1', saved_at: '2026-10-31 12:00:00' })
      await api.listInterviewRecords()
      await api.loadInterviewRecord('record/1')
      await api.deleteInterviewRecord('record/1')
      expect(requests).toHaveLength(4)
      expect(requests[0]).toMatchObject({ method: 'post', url: '/interview-records' })
      expect(requests[0].data).toMatchObject({ expected_user_id: 'user-a', title: '后端工程师 · 第一轮' })
      expect(requests[1]).toMatchObject({ method: 'get', url: '/interview-records' })
      expect(requests[2]).toMatchObject({ method: 'get', url: '/interview-records/record%2F1' })
      expect(requests[3]).toMatchObject({ method: 'delete', url: '/interview-records/record%2F1' })
    } finally {
      requestAdapter.mockReset()
    }
  })

  it('经历库读取和删除会编码路径中的特殊 ID', async () => {
    const requests: Array<{ method?: string; url?: string }> = []
    requestAdapter.mockImplementation(async (config) => {
      requests.push({ method: config.method, url: config.url })
      return { data: { ok: true }, status: 200, statusText: 'OK', headers: {}, config }
    })
    try {
      await api.loadProfile('profile/with space')
      await api.deleteProfile('profile/with space')
      expect(requests).toEqual([
        { method: 'get', url: '/profiles/profile%2Fwith%20space' },
        { method: 'delete', url: '/profiles/profile%2Fwith%20space' },
      ])
    } finally {
      requestAdapter.mockReset()
    }
  })
})
