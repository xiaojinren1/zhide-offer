import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import type { ResumeProfile } from '../lib/types'

const hooks = vi.hoisted(() => ({ slots: [] as any[], cursor: 0, effects: [] as (() => unknown)[] }))
vi.mock('react', async (original) => ({
  ...await original<typeof import('react')>(),
  useState: (initial: unknown) => {
    const index = hooks.cursor++
    if (!(index in hooks.slots)) hooks.slots[index] = typeof initial === 'function' ? initial() : initial
    return [hooks.slots[index], (value: any) => { hooks.slots[index] = typeof value === 'function' ? value(hooks.slots[index]) : value }]
  },
  useRef: (initial: unknown) => {
    const index = hooks.cursor++
    if (!(index in hooks.slots)) hooks.slots[index] = { current: initial }
    return hooks.slots[index]
  },
  useEffect: (effect: () => unknown) => { hooks.effects.push(effect) },
}))
vi.mock('../lib/api', () => ({
  ACCOUNT_CHANGED_EVENT: 'test:account', SESSION_EXPIRED_EVENT: 'test:expired',
  apiErrorMessage: (e: unknown) => e instanceof Error ? e.message : '操作失败',
  api: { me: vi.fn(), listInterviewRecords: vi.fn(), loadInterviewRecord: vi.fn(), deleteInterviewRecord: vi.fn() },
}))
import { ACCOUNT_CHANGED_EVENT, api } from '../lib/api'
import InterviewPage from './InterviewPage'
import { bankFixture, reportFixture, sessionFixture } from './interview/test-support'

const profile: ResumeProfile = { name: '虚构同学', experiences: [{ kind: 'project', name: '预约系统', role: '开发', period: '2025', actions: ['编写接口'], results: ['交付原型'], skills: [] }], skills: ['Python'], education: [], user_confirmed: true }
const fetchMock = vi.fn()
const getRandomValues = globalThis.crypto.getRandomValues.bind(globalThis.crypto)
let pageProps: Parameters<typeof InterviewPage>[0]
function render() { hooks.cursor = 0; hooks.effects = []; return InterviewPage(pageProps) }
function nodes(value: any): any[] {
  if (!value || typeof value !== 'object') return []
  if (Array.isArray(value)) return value.flatMap(nodes)
  return [value, ...nodes(value.props?.children)]
}
function text(value: any): string {
  if (typeof value === 'string' || typeof value === 'number') return String(value)
  if (Array.isArray(value)) return value.map(text).join('')
  return value?.props ? text(value.props.children) : ''
}
function button(label: string) { return nodes(render()).find(node => node.type === 'button' && text(node) === label) }
function answerField() { return nodes(render()).find(node => node.type === 'textarea') }
function answer(value: string) { answerField().props.onChange({ target: { value } }) }
function reply(data: unknown, status = 200) { return new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } }) }
function markup() { return renderToStaticMarkup(render()) }
async function enter() {
  fetchMock.mockResolvedValueOnce(reply({ ok: true, bank: bankFixture() }))
  button('生成个性化题库').props.onClick()
  await vi.waitFor(() => expect(button('从这份题库进入模拟')).toBeDefined())
  button('从这份题库进入模拟').props.onClick()
  fetchMock.mockResolvedValueOnce(reply({ ok: true, session: sessionFixture() }))
  button('开始连续模拟面试').props.onClick()
  await vi.waitFor(() => expect(answerField()).toBeDefined())
  fetchMock.mockClear()
}
async function enterDirect() {
  button('直接进入全真模拟').props.onClick()
  expect(fetchMock).not.toHaveBeenCalled()
  const session = { ...sessionFixture(), mode: 'direct', bank_id: null }
  fetchMock.mockResolvedValueOnce(reply({ ok: true, session }))
  button('开始连续模拟面试').props.onClick()
  await vi.waitFor(() => expect(answerField()).toBeDefined())
  return session
}
async function errorIs(message: string) {
  await vi.waitFor(() => expect(text(render())).toContain(message))
  expect(button('提交回答').props.disabled).toBe(false)
  expect(() => markup()).not.toThrow()
}
beforeEach(() => {
  hooks.slots = []; hooks.cursor = 0; hooks.effects = []; vi.resetAllMocks()
  pageProps = { userId: 'user-a', profile, jdText: 'Python 开发', markdown: '# 虚构简历' }
  vi.stubGlobal('fetch', fetchMock)
  // 公网 HTTP 页面没有 randomUUID；所有入口、回答和报告回归均在该环境运行。
  vi.stubGlobal('crypto', { getRandomValues })
  const target = new EventTarget()
  vi.stubGlobal('window', { addEventListener: target.addEventListener.bind(target), removeEventListener: target.removeEventListener.bind(target), dispatchEvent: target.dispatchEvent.bind(target), setInterval, clearInterval })
  vi.mocked(api.listInterviewRecords).mockResolvedValue({ ok: true, records: [] })
})
afterEach(() => vi.unstubAllGlobals())

describe('continuous interview page', () => {
  it('restores preparation buttons after a bank failure and retries the identical request without randomUUID', async () => {
    expect(globalThis.crypto.randomUUID).toBeUndefined()
    fetchMock.mockResolvedValueOnce(reply({ detail: '题库超时' }, 504))
    button('生成个性化题库').props.onClick()
    await vi.waitFor(() => expect(text(render())).toContain('题库超时'))
    expect(button('生成个性化题库').props.disabled).toBe(false)
    expect(button('直接进入全真模拟').props.disabled).toBe(false)
    const first = JSON.parse(fetchMock.mock.calls[0][1].body)
    expect(first.request_id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/)
    fetchMock.mockResolvedValueOnce(reply({ ok: true, bank: bankFixture() }))
    button('生成个性化题库').props.onClick()
    await vi.waitFor(() => expect(button('从这份题库进入模拟')).toBeDefined())
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual(first)
    expect(text(render())).not.toContain('题库超时')
    expect(button('按当前材料重新生成题库').props.disabled).toBe(false)
  })
  it('shows independent entries and names missing materials without hiding them', () => {
    pageProps = { ...pageProps, profile: null, markdown: '', jdText: '' }
    expect(button('生成个性化题库').props.disabled).toBe(true)
    expect(button('直接进入全真模拟').props.disabled).toBe(true)
    expect(text(render())).toContain('已确认的经历、最新生成的简历、岗位 JD')
    expect(button('全真模拟面试')).toBeDefined()
    expect(fetchMock).not.toHaveBeenCalled()
  })
  it('starts directly with latest materials, without generating a bank or exposing samples', async () => {
    pageProps = { ...pageProps, markdown: '# 最新生成版本\n接口测试项目', jdText: '测试开发工程师\n关注边界测试' }
    await enterDirect()
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls[0][0]).toBe('/api/interview/start')
    const body = JSON.parse(fetchMock.mock.calls[0][1].body)
    expect(body).toMatchObject({ resume_profile: profile, resume_markdown: pageProps.markdown, jd_text: pageProps.jdText })
    expect(body).not.toHaveProperty('bank_id')
    expect(markup()).not.toContain('查看示范回答')
    expect(markup()).not.toContain('核对本轮简历')
    expect(button('生成个性化题库')).toBeUndefined()
  })
  it('keeps a direct start retry identical and ignores double clicks while waiting', async () => {
    button('全真模拟面试').props.onClick()
    let complete!: (r: Response) => void
    fetchMock.mockReturnValueOnce(new Promise<Response>((resolve) => { complete = resolve }))
    const start = button('开始连续模拟面试').props.onClick
    start(); start()
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const first = JSON.parse(fetchMock.mock.calls[0][1].body)
    complete(reply({ detail: '首问超时' }, 504))
    await vi.waitFor(() => expect(text(render())).toContain('首问超时'))
    expect(answerField()).toBeUndefined()
    fetchMock.mockResolvedValueOnce(reply({ ok: true, session: { ...sessionFixture(), mode: 'direct', bank_id: null } }))
    button('开始连续模拟面试').props.onClick()
    await vi.waitFor(() => expect(answerField()).toBeDefined())
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual(first)
  })
  it.each([10, 18, 30])('displays the actual %i-question count and starts from that bank without requiring study', async (count) => {
    fetchMock.mockResolvedValueOnce(reply({ ok: true, bank: bankFixture(count) }))
    button('生成个性化题库').props.onClick()
    await vi.waitFor(() => expect(button('从这份题库进入模拟')).toBeDefined())
    expect(markup()).toContain(`${count} 道个性化题`)
    expect(markup()).toContain(`${count} / ${count}`)
    button('从这份题库进入模拟').props.onClick()
    fetchMock.mockResolvedValueOnce(reply({ ok: true, session: sessionFixture() }))
    button('开始连续模拟面试').props.onClick()
    await vi.waitFor(() => expect(answerField()).toBeDefined())
    expect(fetchMock.mock.calls[1][0]).toBe('/api/interview/start')
    const body = JSON.parse(fetchMock.mock.calls[1][1].body)
    expect(body.bank_id).toBe('bank-test')
    expect(body).not.toHaveProperty('resume_profile')
  })
  it.each([9, 31, -1])('rejects invalid bank size or duplicate questions (%i) without losing the entries', async (count) => {
    const bank = bankFixture(count < 0 ? 10 : count)
    if (count < 0) bank.questions[9].question = bank.questions[0].question
    fetchMock.mockResolvedValueOnce(reply({ ok: true, bank }))
    button('生成个性化题库').props.onClick()
    await vi.waitFor(() => expect(text(render())).toContain('题库内容不完整'))
    expect(button('从这份题库进入模拟')).toBeUndefined()
    expect(button('直接进入全真模拟').props.disabled).toBe(false)
  })
  it('loads schema 3 direct history with a snapshot and themes, without a fictitious bank', async () => {
    const session = await enterDirect()
    const saved = { ...reportFixture(), session: { ...session, status: 'ended' } }
    vi.mocked(api.listInterviewRecords).mockResolvedValue({ ok: true, records: [{ id: 'direct-record', title: '直接模拟', saved_at: '2026-10-31' }] })
    fetchMock.mockResolvedValueOnce(reply(saved))
    button('结束并生成整体报告').props.onClick()
    await vi.waitFor(() => expect(button('返回准备页，开始下一轮')).toBeDefined())
    vi.mocked(api.loadInterviewRecord).mockResolvedValue({ ok: true, record: { id: 'direct-record', title: '直接模拟', saved_at: '2026-10-31', overall_feedback: {
      schema_version: 3, mode: 'direct', bank: null, context: { job_title: 'Python 开发', sources: bankFixture().sources,
        topics: [{ id: 'topic-1', category: 'experience', focus: '个人贡献', source_ids: ['s1'] }], resume_markdown: '# 历史直接模拟', jd_text: 'Python 开发' },
      snapshot: { ...bankFixture().snapshot, resume_markdown: '# 历史直接模拟' }, transcript: session.turns, report: saved.report, elapsed_seconds: 60,
    } } })
    button('面试历史').props.onClick()
    await vi.waitFor(() => expect(button('查看报告与对话')?.props.disabled).toBe(false))
    button('查看报告与对话').props.onClick()
    await vi.waitFor(() => expect(button('返回准备页，开始下一轮')).toBeDefined())
    expect(markup()).toContain('历史直接模拟')
    expect(markup()).toContain('个人贡献')
    expect(button('练习对应主题')).toBeUndefined()
    button('返回准备页，开始下一轮').props.onClick()
    expect(button('直接进入全真模拟').props.disabled).toBe(false)
  })
  it('separates preparation from active conversation with no scores, samples or hints', async () => {
    await enter()
    const html = markup()
    expect(html).toContain('累计用时')
    expect(html).not.toContain('查看示范回答')
    expect(html).not.toContain('推荐回答结构')
    expect(html).not.toContain('分数')
    expect(html).not.toContain('面试历史')
    expect(html).toContain('跳过这道题')
  })
  it('keeps the answer and safely renders 422 detail arrays without a white screen', async () => {
    await enter()
    fetchMock.mockResolvedValueOnce(reply({ detail: [{ msg: 'too long', input: { secret: 'private answer' } }] }, 422))
    answer('我负责预约冲突检查'); button('提交回答').props.onClick()
    await errorIs('提交内容不符合要求')
    expect(answerField().props.value).toBe('我负责预约冲突检查')
    expect(markup()).not.toContain('private answer')
    const first = JSON.parse(fetchMock.mock.calls[0][1].body)
    const next = sessionFixture(); next.version = 2; next.turns[0].answer = '我负责预约冲突检查'
    next.turns.push({ ...next.turns[0], id: 'turn-2', answer: null, question: { ...next.turns[0].question, text: '你如何验证结果？', stage: 'deep_dive' } })
    fetchMock.mockResolvedValueOnce(reply({ ok: true, session: next }))
    button('提交回答').props.onClick()
    await vi.waitFor(() => expect(answerField().props.value).toBe(''))
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual(first)
    expect(text(render())).toContain('你如何验证结果')
  })
  it('blocks blank and oversized answers before any request', async () => {
    await enter(); answer('  '); button('提交回答').props.onClick()
    expect(text(render())).toContain('请输入回答')
    answer('答'.repeat(12001)); button('提交回答').props.onClick()
    expect(text(render())).toContain('最多 12000 字')
    expect(answerField().props.maxLength).toBe(12000)
    expect(fetchMock).not.toHaveBeenCalled()
  })
  it.each([502, 503, 504, 429])('preserves drafts on HTTP %i errors', async (status) => {
    await enter(); fetchMock.mockResolvedValueOnce(reply({ detail: '模型失败，请重试' }, status))
    answer('我的真实回答'); button('提交回答').props.onClick()
    await errorIs('模型失败，请重试'); expect(answerField().props.value).toBe('我的真实回答')
  })
  it('recovers from non-JSON and malformed nested model output', async () => {
    await enter(); fetchMock.mockResolvedValueOnce(new Response('<html>Bad Gateway</html>', { status: 502 }))
    answer('真实回答'); button('提交回答').props.onClick(); await errorIs('模型返回格式无效')
    fetchMock.mockResolvedValueOnce(reply({ ok: true, session: { ...sessionFixture(), turns: [{ question: {} }] } }))
    button('提交回答').props.onClick(); await errorIs('对话内容不完整')
    expect(answerField().props.value).toBe('真实回答')
  })
  it('ignores double clicks synchronously', async () => {
    await enter(); let complete!: (r: Response) => void
    fetchMock.mockReturnValue(new Promise<Response>((resolve) => { complete = resolve }))
    answer('我的真实回答'); const submit = button('提交回答').props.onClick
    submit(); submit(); expect(fetchMock).toHaveBeenCalledTimes(1)
    complete(reply({ detail: '请重试' }, 504)); await errorIs('请重试')
  })
  it('includes the final draft and retries report failures without duplicate submissions', async () => {
    await enter(); answer('最后一条真实回答')
    fetchMock.mockResolvedValueOnce(reply({ detail: '报告超时' }, 504))
    button('提交当前回答并结束').props.onClick()
    await vi.waitFor(() => expect(button('重试生成报告')).toBeDefined())
    expect(answerField()).toBeUndefined()
    const first = JSON.parse(fetchMock.mock.calls[0][1].body)
    expect(first.final_answer).toBe('最后一条真实回答')
    fetchMock.mockResolvedValueOnce(reply(reportFixture(false)))
    button('重试生成报告').props.onClick()
    await vi.waitFor(() => expect(button('重试保存')).toBeDefined())
    expect(markup()).toContain('阶段性反馈')
    fetchMock.mockResolvedValueOnce(reply(reportFixture(true)))
    button('重试保存').props.onClick()
    await vi.waitFor(() => expect(text(render())).toContain('本轮已保存'))
    expect(JSON.parse(fetchMock.mock.calls[2][1].body)).toEqual(first)
    expect(text(render())).not.toContain('逐题评分')
  })
  it('shows the 15-minute advisory while allowing continued answers', async () => {
    await enter(); hooks.slots[10] = 901
    expect(text(render())).toContain('你可以继续回答')
    expect(button('提交回答').props.disabled).toBe(false)
    expect(answerField()).toBeDefined()
  })
  it('requires regeneration before starting a new interview from a history bank', async () => {
    await enter()
    const saved = reportFixture(true)
    vi.mocked(api.listInterviewRecords).mockResolvedValue({ ok: true, records: [{ id: 'old-record', title: '历史面试', saved_at: '2026-10-30' }] })
    fetchMock.mockResolvedValueOnce(reply(saved))
    button('结束并生成整体报告').props.onClick()
    await vi.waitFor(() => expect(button('返回准备页，开始下一轮')).toBeDefined())
    const historicalBank = bankFixture(3)
    vi.mocked(api.loadInterviewRecord).mockResolvedValue({ ok: true, record: { id: 'old-record', title: '历史面试', saved_at: '2026-10-30',
      overall_feedback: { schema_version: 2, bank: historicalBank, snapshot: { ...historicalBank.snapshot, resume_markdown: '# 历史版本' },
        transcript: saved.session.turns, report: saved.report, elapsed_seconds: 10 } } })
    button('面试历史').props.onClick()
    await vi.waitFor(() => expect(button('查看报告与对话')?.props.disabled).toBe(false))
    button('查看报告与对话').props.onClick()
    await vi.waitFor(() => expect(button('返回准备页，开始下一轮')).toBeDefined())
    button('返回准备页，开始下一轮').props.onClick()
    expect(button('从这份题库进入模拟').props.disabled).toBe(true)
    expect(text(render())).toContain('可重新生成题库')
    expect(button('按当前材料重新生成题库').props.disabled).toBe(false)
  })
  it('ignores a late model response after an account change', async () => {
    await enter(); render(); const cleanup = hooks.effects[0]() as () => void
    let complete!: (r: Response) => void
    fetchMock.mockReturnValue(new Promise<Response>((resolve) => { complete = resolve }))
    answer('旧账户回答'); button('提交回答').props.onClick()
    window.dispatchEvent(new Event(ACCOUNT_CHANGED_EVENT))
    complete(reply({ ok: true, session: sessionFixture() }))
    await Promise.resolve(); await Promise.resolve()
    expect(markup()).not.toContain('旧账户回答')
    expect(text(render())).toContain('账户已变化')
    cleanup()
  })
})
