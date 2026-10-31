import { beforeEach, describe, expect, it, vi } from 'vitest'

const hooks = vi.hoisted(() => ({ slots: [] as any[], cursor: 0, cleanup: undefined as undefined | (() => void) }))
vi.mock('react', async (importOriginal) => ({
  ...await importOriginal<typeof import('react')>(),
  useState: (initial: unknown) => {
    const index = hooks.cursor++
    if (!(index in hooks.slots)) hooks.slots[index] = initial
    return [hooks.slots[index], (next: unknown) => { hooks.slots[index] = next }]
  },
  useRef: (initial: unknown) => {
    const index = hooks.cursor++
    if (!(index in hooks.slots)) hooks.slots[index] = { current: initial }
    return hooks.slots[index]
  },
  useEffect: (effect: () => () => void) => { hooks.cleanup ??= effect() },
}))
vi.mock('../../lib/api', () => ({ api: { generateRole: vi.fn() } }))
import { api } from '../../lib/api'
import RoleRequirementsEditor from './RoleRequirementsEditor'

let props: Parameters<typeof RoleRequirementsEditor>[0]
function render() { hooks.cursor = 0; return RoleRequirementsEditor(props) }
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
function control(key: string, value: unknown) { return nodes(render()).find(node => node.props?.[key] === value) }
function button(label: string) { return nodes(render()).find(node => node.type === 'button' && text(node).includes(label)) }
function title(value = '嵌入式开发工程师') { control('id', 'test-jd-title').props.onChange({ target: { value } }) }
async function settle() { for (let i = 0; i < 8; i++) await Promise.resolve() }

beforeEach(() => {
  hooks.slots = []; hooks.cursor = 0; hooks.cleanup = undefined; vi.clearAllMocks()
  props = { id: 'test-jd', jdText: '现有真实 JD', onChange: vi.fn(value => { props.jdText = value }), onBusyChange: vi.fn() }
  vi.mocked(api.generateRole).mockResolvedValue({ ok: true, jd_text: '岗位职责\n- 开发固件\n任职要求\n- C 语言' })
})

describe('岗位名称生成与人工采用（Mock API）', () => {
  it('生成仅预览，编辑和补充后采用才更新最终 JD', async () => {
    title(); button('AI 生成职责与要求').props.onClick(); await settle()
    expect(api.generateRole).toHaveBeenCalledWith('嵌入式开发工程师')
    expect(props.onChange).not.toHaveBeenCalled()
    expect(control('id', 'test-jd').props.value).toBe('现有真实 JD')
    expect(text(render())).toContain('岗位参考预览')
    control('aria-label', '编辑岗位参考').props.onChange({ target: { value: '固件开发\n补充：参与硬件联调' } })
    button('采用岗位要求').props.onClick()
    expect(props.onChange).toHaveBeenCalledWith('固件开发\n补充：参与硬件联调')
    expect(text(render())).not.toContain('岗位参考预览')
  })
  it('参考清空后仍可继续编辑，空参考不能采用，放弃不改变最终 JD', async () => {
    title(); button('AI 生成职责与要求').props.onClick(); await settle()
    control('aria-label', '编辑岗位参考').props.onChange({ target: { value: '' } })
    expect(control('aria-label', '编辑岗位参考')).toBeDefined()
    expect(button('采用岗位要求').props.disabled).toBe(true)
    button('采用岗位要求').props.onClick()
    expect(props.onChange).not.toHaveBeenCalled()
    button('放弃参考').props.onClick()
    expect(text(render())).not.toContain('岗位参考预览')
  })
  it('保留直接粘贴真实 JD 和手工追加职责', () => {
    control('id', 'test-jd').props.onChange({ target: { value: '真实 JD\n补充职责：编写测试' } })
    expect(props.onChange).toHaveBeenCalledWith('真实 JD\n补充职责：编写测试')
    expect(api.generateRole).not.toHaveBeenCalled()
  })
  it.each([{ ok: true, jd_text: ' ' }, { ok: false, error: '模型服务失败' }])('空响应或失败保留原 JD 并释放 busy', async result => {
    vi.mocked(api.generateRole).mockResolvedValueOnce(result)
    title(); button('AI 生成职责与要求').props.onClick(); await settle()
    expect(control('role', 'alert')).toBeDefined()
    expect(props.onChange).not.toHaveBeenCalled()
    expect(props.onBusyChange).toHaveBeenLastCalledWith(false)
    expect(button('AI 生成职责与要求').props.disabled).toBe(false)
  })
  it('同步锁阻止重复请求，最终 JD 变化后丢弃迟到结果', async () => {
    let resolve!: (value: any) => void
    vi.mocked(api.generateRole).mockReturnValueOnce(new Promise(done => { resolve = done }))
    title(); const run = button('AI 生成职责与要求').props.onClick
    run(); run()
    expect(api.generateRole).toHaveBeenCalledTimes(1)
    props.jdText = '新 JD'; render()
    resolve({ ok: true, jd_text: '旧参考' }); await settle()
    expect(text(render())).not.toContain('岗位参考预览')
    expect(props.onChange).not.toHaveBeenCalled()
  })
  it('卸载后不采用迟到结果，岗位名称过长不调用模型', async () => {
    title('岗'.repeat(121)); button('AI 生成职责与要求').props.onClick(); await settle()
    expect(api.generateRole).not.toHaveBeenCalled()
    expect(text(render())).toContain('岗位名称不能超过 120 字')
    title(); let resolve!: (value: any) => void
    vi.mocked(api.generateRole).mockReturnValueOnce(new Promise(done => { resolve = done }))
    button('AI 生成职责与要求').props.onClick(); hooks.cleanup?.()
    resolve({ ok: true, jd_text: '迟到参考' }); await settle()
    expect(props.onChange).not.toHaveBeenCalled()
    expect(text(render())).not.toContain('岗位参考预览')
  })
})
