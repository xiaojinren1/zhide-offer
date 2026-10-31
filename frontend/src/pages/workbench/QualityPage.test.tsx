import { beforeEach, describe, expect, it, vi } from 'vitest'

const hooks = vi.hoisted(() => ({ slots: [] as any[], cursor: 0, cleanup: undefined as undefined | (() => void) }))
vi.mock('react', async importOriginal => ({
  ...await importOriginal<typeof import('react')>(),
  useState: (initial: unknown) => {
    const index = hooks.cursor++
    if (!(index in hooks.slots)) hooks.slots[index] = initial
    return [hooks.slots[index], (next: any) => { hooks.slots[index] = typeof next === 'function' ? next(hooks.slots[index]) : next }]
  },
  useRef: (initial: unknown) => {
    const index = hooks.cursor++
    if (!(index in hooks.slots)) hooks.slots[index] = { current: initial }
    return hooks.slots[index]
  },
  useEffect: (effect: () => () => void) => { hooks.cleanup ??= effect() },
}))
vi.mock('../../lib/api', () => ({ api: { quality: vi.fn(), reviseResume: vi.fn() }, apiErrorMessage: (error: Error) => error.message }))
import { api } from '../../lib/api'
import QualityPage from '../QualityPage'

let props: Parameters<typeof QualityPage>[0]
function render() { hooks.cursor = 0; return QualityPage(props) }
function nodes(node: any): any[] {
  if (!node || typeof node !== 'object') return []
  if (Array.isArray(node)) return node.flatMap(nodes)
  return [node, ...nodes(node.props?.children)]
}
function text(node: any): string {
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(text).join('')
  return node?.props ? text(node.props.children) : ''
}
function button(label: string) { return nodes(render()).find(node => node.type === 'button' && text(node).includes(label)) }
async function settle() { for (let i = 0; i < 8; i++) await Promise.resolve() }
const report = () => ({ ok: true, passed: false, keyword_coverage: 0, quantified_ratio: 0, cliche_hits: ['责任心强'], ats_issues: [], consistency_issues: [], suspicions: [] })
async function check() { button('检查当前简历').props.onClick(); await settle() }

beforeEach(() => {
  hooks.slots = []; hooks.cursor = 0; hooks.cleanup = undefined; vi.clearAllMocks()
  props = { jdText: '', jdKeywords: [], profile: { name: '测试同学', user_confirmed: true, experiences: [], education: [], skills: [] },
    markdown: '# 现有稿', busy: false, onMarkdownChange: vi.fn(value => { props.markdown = value }),
    onBusyChange: vi.fn(value => { props.busy = value }), onNext: vi.fn() }
  vi.mocked(api.quality).mockResolvedValue(report())
  vi.mocked(api.reviseResume).mockResolvedValue({ ok: true, markdown: '# 修改稿' })
})

describe('简历检查与当前稿循环（Mock API）', () => {
  it('无JD可检查，采纳更新同一稿并再次检查，不以未通过阻止预览', async () => {
    await check()
    expect(api.quality).toHaveBeenCalledWith('', props.profile, '# 现有稿', [])
    expect(text(render())).toContain('岗位关键词指标不适用')
    expect(text(render())).not.toContain('JD 关键词覆盖率')
    expect(button('查看最终简历').props.disabled).toBe(false)
    const checkbox = nodes(render()).find(node => node.type === 'input' && node.props.type === 'checkbox')
    checkbox.props.onChange()
    button('采纳选中建议并修改简历').props.onClick(); await settle()
    expect(props.markdown).toBe('# 修改稿')
    expect(text(render())).toContain('已应用 1 条建议')
    expect(text(render())).not.toContain('可采纳建议（')
    button('再次检查简历').props.onClick(); await settle()
    expect(api.quality).toHaveBeenLastCalledWith('', props.profile, '# 修改稿', [])
    button('全部采纳并修改简历').props.onClick(); await settle()
    expect(api.reviseResume).toHaveBeenCalledTimes(2)
  })
  it('修订失败保留原稿及建议，解除全局忙碌后可重试', async () => {
    await check()
    vi.mocked(api.reviseResume).mockRejectedValueOnce(new Error('修订服务失败'))
    button('全部采纳并修改简历').props.onClick(); await settle()
    expect(props.markdown).toBe('# 现有稿')
    expect(text(render())).toContain('修订服务失败')
    expect(props.busy).toBe(false)
    expect(button('全部采纳并修改简历').props.disabled).toBe(false)
  })
  it('事实未确认不能应用，检查期间按钮与导航锁定且重复点击只发一次', async () => {
    let resolve!: (value: any) => void
    vi.mocked(api.quality).mockReturnValueOnce(new Promise(done => { resolve = done }))
    const action = button('检查当前简历')
    action.props.onClick(); action.props.onClick()
    expect(api.quality).toHaveBeenCalledTimes(1)
    expect(props.busy).toBe(true)
    resolve(report()); await settle()
    props.profile = { ...props.profile!, user_confirmed: false }
    await check()
    expect(button('全部采纳并修改简历').props.disabled).toBe(true)
    button('全部采纳并修改简历').props.onClick(); await settle()
    expect(api.reviseResume).not.toHaveBeenCalled()
  })
  it.each(['jd', 'markdown', 'profile', 'aba', 'unmount'])('检查迟到响应不展示过期报告：%s', async kind => {
    let resolve!: (value: any) => void
    vi.mocked(api.quality).mockReturnValueOnce(new Promise(done => { resolve = done }))
    button('检查当前简历').props.onClick()
    if (kind === 'jd') props.jdText = '新岗位'
    if (kind === 'markdown') props.markdown = '# 新稿'
    if (kind === 'profile') props.profile = { ...props.profile!, name: '新姓名' }
    if (kind === 'aba') { props.jdText = '临时JD'; render(); props.jdText = '' }
    if (kind === 'unmount') hooks.cleanup?.()
    else render()
    resolve(report()); await settle()
    expect(text(render())).not.toContain('可采纳建议（')
    expect(props.onMarkdownChange).not.toHaveBeenCalled()
  })
  it.each(['markdown', 'aba', 'unmount'])('修订迟到响应不覆盖新稿：%s', async kind => {
    await check()
    let resolve!: (value: any) => void
    vi.mocked(api.reviseResume).mockReturnValueOnce(new Promise(done => { resolve = done }))
    const action = button('全部采纳并修改简历')
    action.props.onClick(); action.props.onClick()
    expect(api.reviseResume).toHaveBeenCalledTimes(1)
    if (kind === 'markdown') props.markdown = '# 用户新稿'
    if (kind === 'aba') { props.jdText = '临时'; render(); props.jdText = '' }
    if (kind === 'unmount') hooks.cleanup?.()
    else render()
    resolve({ ok: true, markdown: '# 过期修订' }); await settle()
    expect(props.onMarkdownChange).not.toHaveBeenCalled()
    expect(props.markdown).not.toBe('# 过期修订')
  })
  it('超过30条不截断、不调用修订，明确提示分批', async () => {
    vi.mocked(api.quality).mockResolvedValueOnce({ ...report(), cliche_hits: Array.from({ length: 31 }, (_, i) => `套话${i}`) })
    await check()
    button('全部采纳并修改简历').props.onClick(); await settle()
    expect(text(render())).toContain('每次最多应用 30 条建议')
    expect(api.reviseResume).not.toHaveBeenCalled()
    expect(props.markdown).toBe('# 现有稿')
  })
})
