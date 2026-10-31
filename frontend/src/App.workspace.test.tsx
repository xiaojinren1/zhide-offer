import { beforeEach, describe, expect, it, vi } from 'vitest'

const hooks = vi.hoisted(() => ({ slots: [] as any[], cursor: 0 }))
const workspace = vi.hoisted(() => ({ state: {} as any, phase: 'conflict', loaded: true, error: '', savedAt: null,
  update: vi.fn(), load: vi.fn(), hasUnsaved: vi.fn(() => false), flush: vi.fn(), retrySave: vi.fn() }))
vi.mock('react', async importOriginal => ({
  ...await importOriginal<typeof import('react')>(),
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
  useCallback: (callback: unknown) => callback,
  useEffect: () => {},
}))
vi.mock('./lib/useWorkspace', () => ({ useWorkspace: () => workspace }))
import App from './App'
import WorkbenchPage from './pages/WorkbenchPage'
import QualityPage from './pages/QualityPage'
import InterviewPage from './pages/InterviewPage'

function nodes(node: any): any[] {
  if (!node || typeof node !== 'object') return []
  if (Array.isArray(node)) return node.flatMap(nodes)
  return [node, ...nodes(node.props?.children)]
}
function text(node: any): string {
  if (typeof node === 'string') return node
  if (Array.isArray(node)) return node.map(text).join('')
  return node?.props ? text(node.props.children) : ''
}
let render: () => any
beforeEach(() => {
  vi.clearAllMocks()
  workspace.loaded = true
  workspace.state = { page: 'workbench', profile: null, jd_text: '岗位', jd_keywords: [], markdown: '', source_text: '', source_name: '' }
  hooks.slots = [{ id: 'mock-account', username: 'mock-account' }, false, '', '']; hooks.cursor = 0
  const account = nodes(App()).find(node => node.type?.name === 'AccountWorkspace')
  hooks.slots = []
  render = () => { hooks.cursor = 0; return account.type(account.props) }
})

describe('模型请求期间的工作台恢复保护', () => {
  it('首次恢复及显式重新载入完成前不挂载工作台，完成后使用恢复稿', () => {
    workspace.loaded = false
    expect(nodes(render()).some(node => node.type === WorkbenchPage)).toBe(false)
    workspace.state = { ...workspace.state, profile: { user_confirmed: true }, markdown: '# 恢复稿' }
    workspace.loaded = true
    let workbench = nodes(render()).find(node => node.type === WorkbenchPage)
    expect(workbench.props.markdown).toBe('# 恢复稿')
    expect(workbench.props.profile.user_confirmed).toBe(true)
    workspace.loaded = false
    expect(nodes(render()).some(node => node.type === WorkbenchPage)).toBe(false)
    workspace.state = { ...workspace.state, markdown: '# 服务器最新稿' }
    workspace.loaded = true
    workbench = nodes(render()).find(node => node.type === WorkbenchPage)
    expect(workbench.props.markdown).toBe('# 服务器最新稿')
  })
  it('填写JD只清关键词，不清当前稿或事实确认', () => {
    workspace.state = { ...workspace.state, profile: { user_confirmed: true }, markdown: '# 当前稿', jd_keywords: ['旧关键词'] }
    const workbench = nodes(render()).find(node => node.type === WorkbenchPage)
    workbench.props.onJdChange('新JD')
    const next = workspace.update.mock.calls.at(-1)![0](workspace.state)
    expect(next).toMatchObject({ jd_text: '新JD', jd_keywords: [], markdown: '# 当前稿', profile: { user_confirmed: true } })
  })
  it('无JD的旧质检路由可恢复，面试需目标岗位与已确认稿', () => {
    workspace.state = { ...workspace.state, page: 'quality', jd_text: '', profile: { user_confirmed: true }, markdown: '# 当前稿' }
    expect(nodes(render()).some(node => node.type === QualityPage)).toBe(true)
    workspace.state.page = 'interview'
    expect(nodes(render()).some(node => node.type === InterviewPage)).toBe(false)
    workspace.state.jd_text = '岗位要求'
    expect(nodes(render()).some(node => node.type === InterviewPage)).toBe(true)
    workspace.state.profile.user_confirmed = false
    expect(nodes(render()).some(node => node.type === InterviewPage)).toBe(false)
  })
  it('旧质检的最终简历入口传递预览意图，返回修改仍进入优化且不改稿', () => {
    workspace.state = { ...workspace.state, page: 'quality', profile: { user_confirmed: true }, markdown: '# 已编辑稿' }
    workspace.update.mockImplementation(update => { workspace.state = update(workspace.state) })
    const quality = nodes(render()).find(node => node.type === QualityPage)
    quality.props.onNext()
    let workbench = nodes(render()).find(node => node.type === WorkbenchPage)
    expect(workbench.props.initialStep).toBe(4)
    expect(workbench.props.markdown).toBe('# 已编辑稿')
    expect(workspace.state.page).toBe('workbench')
    expect(workspace.state).not.toHaveProperty('initialStep')
    workspace.state.page = 'quality'
    nodes(render()).find(node => node.type === QualityPage).props.onEditResume()
    workbench = nodes(render()).find(node => node.type === WorkbenchPage)
    expect(workbench.props.initialStep).toBe(3)
    expect(workbench.props.markdown).toBe('# 已编辑稿')
  })
  it.each([
    ['conflict', '放弃本页编辑并加载服务器版本'],
    ['load-error', '重试恢复'],
  ])('%s 入口禁用且旧事件处理器也不加载，结束后恢复', (phase, label) => {
    workspace.phase = phase
    const original = render()
    const button = nodes(original).find(node => node.type === 'button' && text(node) === label)
    const workbench = nodes(original).find(node => node.type === WorkbenchPage)
    workbench.props.onBusyChange(true)
    button.props.onClick()
    expect(workspace.load).not.toHaveBeenCalled()
    expect(nodes(render()).find(node => node.type === 'button' && text(node) === label).props.disabled).toBe(true)
    workbench.props.onBusyChange(false)
    expect(nodes(render()).find(node => node.type === 'button' && text(node) === label).props.disabled).toBe(false)
    button.props.onClick()
    expect(workspace.load).toHaveBeenCalledTimes(1)
  })
})
