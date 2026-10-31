import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import type { ResumeProfile } from '../lib/types'

// 与项目现有工作台测试一致：执行真实页面处理器，不冒充浏览器布局测试。
const hooks = vi.hoisted(() => ({ slots: [] as any[], cursor: 0, effect: null as (() => void | (() => void)) | null }))
vi.mock('react', async (original) => ({
  ...await original<typeof import('react')>(),
  useState: (initial: unknown) => {
    const index = hooks.cursor++
    if (!(index in hooks.slots)) hooks.slots[index] = initial
    return [hooks.slots[index], (value: any) => { hooks.slots[index] = typeof value === 'function' ? value(hooks.slots[index]) : value }]
  },
  useRef: (initial: unknown) => {
    const index = hooks.cursor++
    if (!(index in hooks.slots)) hooks.slots[index] = { current: initial }
    return hooks.slots[index]
  },
  useEffect: (effect: () => void | (() => void)) => { hooks.effect = effect },
}))
vi.mock('../lib/api', () => ({
  api: { listProfiles: vi.fn(), loadProfile: vi.fn(), deleteProfile: vi.fn() },
  apiErrorMessage: (error: unknown) => error instanceof Error ? error.message : '失败',
  ACCOUNT_CHANGED_EVENT: 'zhide:account-changed', SESSION_EXPIRED_EVENT: 'zhide:session-expired',
}))
import { api } from '../lib/api'
import MemoryPage, { profileForWorkbench } from './MemoryPage'

const profile = (): ResumeProfile => ({ name: '虚构同学', experiences: [{ kind: 'project', name: '示例项目', role: '成员', period: '2026', actions: ['整理需求'], results: ['输出文档'], skills: [] }], education: [], skills: [], user_confirmed: true })
const item = { id: 'demo-id', name: '虚构经历库', saved_at: '2026-10-31 10:00:00', experience_count: 1 }
let props: Parameters<typeof MemoryPage>[0]
let cleanup: (() => void) | void
function render() { hooks.cursor = 0; return MemoryPage(props) }
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
function click(label: string) {
  const button = nodes(render()).find(node => node.type === 'button' && text(node).includes(label))
  if (!button || button.props.disabled) throw new Error(`按钮不可用：${label}`)
  return button.props.onClick()
}
async function settle() { for (let i = 0; i < 10; i++) await Promise.resolve() }
async function mount() { render(); cleanup = hooks.effect?.(); await settle() }

beforeEach(() => {
  hooks.slots = []; hooks.cursor = 0; hooks.effect = null; vi.resetAllMocks()
  vi.stubGlobal('window', new EventTarget())
  props = { userId: 'account-a', onLoad: vi.fn() }
  vi.mocked(api.listProfiles).mockResolvedValue({ ok: true, profiles: [item] })
  vi.mocked(api.loadProfile).mockResolvedValue({ ok: true, profile: profile(), meta: item })
  vi.mocked(api.deleteProfile).mockResolvedValue({ ok: true })
})
afterEach(() => { cleanup?.(); cleanup = undefined; vi.unstubAllGlobals() })

describe('personal memory', () => {
  it('loads the list and shows name, date and count', async () => {
    await mount()
    expect(api.listProfiles).toHaveBeenCalledOnce()
    const output = text(render())
    expect(output).toContain(item.name)
    expect(output).toContain(item.saved_at)
    expect(output).toContain('1 段经历')
  })
  it('provides an empty state and lets failed requests retry', async () => {
    vi.mocked(api.listProfiles).mockRejectedValueOnce(new Error('读取失败'))
    await mount()
    expect(text(render())).toContain('读取失败')
    vi.mocked(api.listProfiles).mockResolvedValueOnce({ ok: true, profiles: [] })
    click('刷新列表'); await settle()
    expect(text(render())).toContain('还没有保存的经历库')
  })
  it('previews then loads an independent, unconfirmed copy only on confirmation', async () => {
    await mount(); click('查看 虚构'); await settle()
    expect(props.onLoad).not.toHaveBeenCalled()
    expect(text(render())).toContain('整理需求')
    click('确认替换材料并载入')
    expect(props.onLoad).toHaveBeenCalledWith(expect.objectContaining({ user_confirmed: false }), item)
    const saved = profile(); const clone = profileForWorkbench(saved)
    clone.experiences[0].actions.push('独立修改')
    expect(saved.experiences[0].actions).toEqual(['整理需求'])
    expect(saved.user_confirmed).toBe(true)
  })
  it('requires deletion confirmation, retains errors and supports retry', async () => {
    await mount(); click('删除 虚构')
    expect(api.deleteProfile).not.toHaveBeenCalled()
    vi.mocked(api.deleteProfile).mockRejectedValueOnce(new Error('删除失败'))
    click('确认永久删除'); await settle()
    expect(text(render())).toContain('删除失败')
    expect(text(render())).toContain('虚构经历库')
    click('确认永久删除'); await settle()
    expect(api.deleteProfile).toHaveBeenCalledTimes(2)
    expect(text(render())).toContain('还没有保存的经历库')
    expect(props.onLoad).not.toHaveBeenCalled()
  })
  it('cancels deletion without sending a request', async () => {
    await mount(); click('删除 虚构'); click('取消删除')
    expect(api.deleteProfile).not.toHaveBeenCalled()
    expect(text(render())).not.toContain('确认永久删除')
  })
  it('discards a late detail response after account change', async () => {
    let resolve: (value: any) => void = () => {}
    vi.mocked(api.loadProfile).mockImplementation(() => new Promise(done => { resolve = done }))
    await mount(); click('查看 虚构')
    window.dispatchEvent(new Event('zhide:account-changed'))
    resolve({ ok: true, profile: profile(), meta: item }); await settle()
    expect(text(render())).not.toContain('示例项目')
    expect(text(render())).not.toContain(item.name)
    expect(text(render())).toContain('账户状态已变化')
    expect(props.onLoad).not.toHaveBeenCalled()
  })
  it('rejects malformed saved profiles rather than crashing the preview', async () => {
    vi.mocked(api.loadProfile).mockResolvedValue({ ok: true, profile: { ...profile(), experiences: [null] } as any, meta: item })
    await mount(); click('查看 虚构'); await settle()
    expect(text(render())).toContain('经历库结构不完整')
  })
  it('ignores a late list after unmount and blocks empty exports', async () => {
    let resolve: (value: any) => void = () => {}
    vi.mocked(api.listProfiles).mockImplementation(() => new Promise(done => { resolve = done }))
    render(); cleanup = hooks.effect?.(); cleanup?.(); cleanup = undefined
    resolve({ ok: true, profiles: [item] }); await settle()
    expect(text(render())).not.toContain(item.name)
    for (const label of ['下载 Markdown', '下载 Word']) {
      const button = nodes(render()).find(node => node.type === 'button' && text(node).includes(label))
      expect(button.props.disabled).toBe(true)
    }
  })
})
