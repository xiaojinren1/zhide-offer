import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AxiosError, AxiosHeaders } from 'axios'
import type { ResumeProfile } from '../../lib/types'

// 无额外 DOM 依赖的处理器测试：真实页面函数与事件回调，模拟 hook 重渲染及 API。
// 不替代浏览器布局、焦点或真实模型验收。
const hooks = vi.hoisted(() => ({ slots: [] as any[], cursor: 0 }))
vi.mock('react', async (importOriginal) => ({
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
  useEffect: () => {},
}))
vi.mock('../../lib/api', async (importOriginal) => ({ ...await importOriginal<typeof import('../../lib/api')>(), api: { parseResumeText: vi.fn(), parseResumeFile: vi.fn(), parseResumeImage: vi.fn(), generateResume: vi.fn(), diagnose: vi.fn(), saveProfile: vi.fn() } }))
import { api } from '../../lib/api'
import WorkbenchPage from '../WorkbenchPage'
import DiagnosePage from '../DiagnosePage'
import ImportReview from '../library/ImportReview'

const fixture = (): ResumeProfile => ({ name: '虚构同学', experiences: [{ kind: 'project', name: '校园项目', role: '成员', period: '', actions: ['整理反馈'], results: ['输出文档'], skills: [] }], skills: [], education: [], user_confirmed: true })
let props: Parameters<typeof WorkbenchPage>[0]
function render() { hooks.cursor = 0; return WorkbenchPage(props) }
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
function button(tree: any, label: string) {
  const found = nodes(tree).find((n) => n.type === 'button' && text(n).includes(label))
  if (!found) throw new Error(`未找到按钮：${label}`)
  return found
}
function input(tree: any, key: string, value: unknown) {
  return nodes(tree).find((n) => n.props?.[key] === value)
}
async function settle() { for (let i = 0; i < 6; i++) await Promise.resolve() }

beforeEach(() => {
  hooks.slots = []; hooks.cursor = 0; vi.clearAllMocks(); vi.unstubAllGlobals()
  props = { sourceText: '', sourceName: '', setSourceText: (value) => { props.sourceText = value }, setSourceName: (value) => { props.sourceName = value },
    profile: fixture(), jdText: '虚构岗位 JD', markdown: '', jdKeywords: [], busy: false,
    onProfileChange: (value) => { props.profile = value }, onJdChange: (value) => { props.jdText = value },
    onMarkdownChange: (value) => { props.markdown = value }, onBusyChange: (value) => { props.busy = value }, onInterview: vi.fn() }
  vi.mocked(api.parseResumeText).mockResolvedValue({ ok: true, profile: fixture(), raw_text: '虚构经历' })
  vi.mocked(api.parseResumeImage).mockResolvedValue({ ok: true, profile: fixture(), raw_text: '[图片材料：resume.png]' })
  vi.mocked(api.generateResume).mockResolvedValue({ ok: true, markdown: '# 虚构同学' })
  vi.mocked(api.saveProfile).mockResolvedValue({ ok: true, id: 'saved-id', saved_at: '2026-10-31 12:00:00' })
})

describe('工作台真实事件回调（Mock API）', () => {
  it('清除文本同时清除来源、事实和旧稿，保留岗位 JD 且阻止下一步', () => {
    props.sourceText = '虚构材料'; props.sourceName = 'resume.pdf'; props.markdown = '# 旧稿'
    button(render(), '清除文本').props.onClick()
    expect(props.sourceText).toBe(''); expect(props.sourceName).toBe('')
    expect(props.profile).toBeNull(); expect(props.markdown).toBe('')
    expect(props.jdText).toBe('虚构岗位 JD')
    expect(button(render(), '下一步：确认事实').props.disabled).toBe(true)
    expect(button(render(), '清除文本').props.disabled).toBe(true)
  })
  it('取消移除保留所有材料，确认后才清空当前工作台', () => {
    props.sourceText = '虚构材料'; props.sourceName = 'resume.pdf'; props.markdown = '# 旧稿'
    const confirm = vi.fn().mockReturnValueOnce(false).mockReturnValueOnce(true)
    vi.stubGlobal('window', { confirm })
    const originalProfile = props.profile
    input(render(), 'aria-label', '移除材料：resume.pdf').props.onClick()
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('resume.pdf'))
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('保留岗位 JD'))
    expect(props.sourceText).toBe('虚构材料'); expect(props.sourceName).toBe('resume.pdf')
    expect(props.profile).toBe(originalProfile); expect(props.markdown).toBe('# 旧稿')
    input(render(), 'aria-label', '移除材料：resume.pdf').props.onClick()
    expect(props.sourceText).toBe(''); expect(props.sourceName).toBe('')
    expect(props.profile).toBeNull(); expect(props.markdown).toBe('')
    expect(props.jdText).toBe('虚构岗位 JD')
  })
  it('处理中拒绝清除或移除材料', () => {
    props.sourceText = '虚构材料'; props.sourceName = 'resume.pdf'; props.busy = true
    const confirm = vi.fn(); vi.stubGlobal('window', { confirm })
    expect(button(render(), '清除文本').props.disabled).toBe(true)
    button(render(), '清除文本').props.onClick()
    input(render(), 'aria-label', '移除材料：resume.pdf').props.onClick()
    expect(confirm).not.toHaveBeenCalled(); expect(props.sourceText).toBe('虚构材料')
    expect(props.sourceName).toBe('resume.pdf'); expect(props.profile).not.toBeNull()
  })
  const tailored = () => ({ version: 1, selected_experiences: [{ id: 'e1', name: '校园项目' }],
    requirements: [{ id: 'r1', requirement: '整理反馈', priority: 'core', status: 'supported',
      evidence: [{ id: 'e1.actions.1', text: '整理反馈', experience_id: 'e1', experience_name: '校园项目', field: 'actions' }], output_excerpt: '整理反馈' },
      { id: 'r2', requirement: '熟悉 Java', priority: 'support', status: 'gap', evidence: [], output_excerpt: '' }],
    unsupported_claims: [], review_note: '模型复核不是事实认证。' })
  it('展示岗位要求、真实依据、正文摘录和缺口，编辑后隐藏旧定制报告', async () => {
    props.jdText = '整理反馈，熟悉 Java'
    vi.mocked(api.generateResume).mockResolvedValueOnce({ ok: true, markdown: '# 虚构同学\n整理反馈', tailoring: tailored() } as any)
    button(render(), '根据已确认事实生成简历').props.onClick(); await settle()
    const page = text(render())
    expect(page).toContain('这份简历如何针对岗位调整')
    expect(page).toContain('有相关依据与正文摘录')
    expect(page).toContain('本稿摘录：整理反馈')
    expect(page).toContain('Java — 缺少事实依据')
    button(render(), '编辑').props.onClick()
    input(render(), 'aria-label', '编辑简历 Markdown').props.onChange({ target: { value: '# 修改稿' } })
    expect(text(render())).toContain('定制依据待核对')
    expect(text(render())).not.toContain('本稿摘录：整理反馈')
  })
  it('有事实但通用润色未体现时明确提示，不当作定制完成', async () => {
    props.jdText = '整理反馈，熟悉 Java'
    const report = tailored(); report.requirements[0].output_excerpt = ''
    vi.mocked(api.generateResume).mockResolvedValueOnce({ ok: true, markdown: '# 普通润色', tailoring: report } as any)
    button(render(), '根据已确认事实生成简历').props.onClick(); await settle()
    expect(text(render())).toContain('有依据但正文未体现')
    expect(text(render())).toContain('不能仅视作定制完成')
  })
  it('自动修订后展示次数，仍未体现的要求继续警告', async () => {
    props.jdText = '整理反馈，熟悉 Java'
    const report = { ...tailored(), revision_count: 1 }; report.requirements[0].output_excerpt = ''
    vi.mocked(api.generateResume).mockResolvedValueOnce({ ok: true, markdown: '# 普通润色', tailoring: report } as any)
    button(render(), '根据已确认事实生成简历').props.onClick(); await settle()
    expect(text(render())).toContain('已自动定向修订 1 次并重新复核')
    expect(text(render())).toContain('有依据但正文未体现')
    expect(text(render())).toContain('不代表已通过')
  })
  it('缺失或坏报告不阻止查看草稿，但不能展示旧的定制依据', async () => {
    props.jdText = '整理反馈，熟悉 Java'
    const report = tailored(); report.requirements[0].evidence[0].text = '虚构行动'
    vi.mocked(api.generateResume).mockResolvedValueOnce({ ok: true, markdown: '# 草稿', tailoring: report } as any)
    button(render(), '根据已确认事实生成简历').props.onClick(); await settle()
    expect(props.markdown).toBe('# 草稿')
    expect(text(render())).toContain('定制依据待核对')
    expect(text(render())).not.toContain('虚构行动')
  })
  it('恢复其他稿件不复用原定制报告', async () => {
    props.jdText = '整理反馈，熟悉 Java'
    vi.mocked(api.generateResume).mockResolvedValueOnce({ ok: true, markdown: '# 虚构同学\n整理反馈', tailoring: tailored() } as any)
    button(render(), '根据已确认事实生成简历').props.onClick(); await settle()
    expect(text(render())).toContain('本稿摘录：整理反馈')
    props.markdown = '# 恢复稿'
    expect(text(render())).toContain('定制依据待核对')
    expect(text(render())).not.toContain('本稿摘录：整理反馈')
  })
  it('保留解析出的教育卡，无需补写成果即可确认和生成', async () => {
    props.profile = { ...fixture(), user_confirmed: false, experiences: [{ kind: 'education', name: '虚构大学', role: '本科', period: '2022—2026', actions: [], results: [], skills: [] }, ...fixture().experiences] }
    expect(input(render(), 'type', 'checkbox').props.disabled).toBe(false)
    expect(text(render())).toContain('教育仅记录学校、专业学历和起止时间')
    input(render(), 'type', 'checkbox').props.onChange({ target: { checked: true } })
    button(render(), '根据已确认事实生成简历').props.onClick(); await settle()
    expect(api.generateResume).toHaveBeenCalledWith(props.jdText, expect.objectContaining({ experiences: expect.arrayContaining([expect.objectContaining({ kind: 'education', actions: [], results: [] })]) }), [])
  })
  it('展示后端质检失败而非无条件绿色成功', async () => {
    vi.mocked(api.generateResume).mockResolvedValueOnce({ ok: true, markdown: '# 待核对稿件', traceability_passed: true, self_check: { passed: false, issues_remaining: 5, high_remaining: 1 } } as any)
    button(render(), '根据已确认事实生成简历').props.onClick(); await settle()
    expect(props.markdown).toBe('# 待核对稿件')
    expect(text(render())).toContain('质检未通过 · 草稿待核对')
    expect(text(render())).toContain('剩余 5 项问题，其中高风险 1 项')
    expect(nodes(render()).some(n => n.props?.className === 'wb-success')).toBe(false)
  })
  it('自动检查完成仍提示逐句核对，编辑后不沿用通过状态', async () => {
    vi.mocked(api.generateResume).mockResolvedValueOnce({ ok: true, markdown: '# 初稿', traceability_passed: true, self_check: { passed: true, issues_remaining: 0, high_remaining: 0 } } as any)
    button(render(), '根据已确认事实生成简历').props.onClick(); await settle()
    expect(text(render())).toContain('自动检查完成 · 仍需事实核对')
    button(render(), '编辑').props.onClick()
    input(render(), 'aria-label', '编辑简历 Markdown').props.onChange({ target: { value: '# 编辑稿' } })
    expect(text(render())).not.toContain('自动检查完成 · 仍需事实核对')
    expect(text(render())).toContain('质检状态未知')
  })
  it('恢复的稿件不复用其他输入的数字与质检警告', async () => {
    vi.mocked(api.generateResume).mockResolvedValueOnce({ ok: true, markdown: '# 原稿', untraceable: ['原稿数字警告'], self_check: { passed: false, issues_remaining: 5, high_remaining: 1 } } as any)
    button(render(), '根据已确认事实生成简历').props.onClick(); await settle()
    expect(text(render())).toContain('原稿数字警告')
    props.markdown = '# 恢复的稿件'; props.sourceText = '恢复的材料'
    expect(text(render())).not.toContain('原稿数字警告')
    expect(text(render())).not.toContain('剩余 5 项问题')
    expect(text(render())).toContain('质检状态未知')
  })
  it('不调用解析 API 也能手工填写、确认并生成', async () => {
    props.profile = null; props.sourceText = '原始虚构经历'
    button(render(), '直接手工填写事实').props.onClick()
    expect(props.profile).toMatchObject({ raw_text: '原始虚构经历' })
    expect(input(render(), 'type', 'checkbox').props.disabled).toBe(true)
    input(render(), 'aria-label', '经历1名称').props.onChange({ target: { value: '校园项目' } })
    input(render(), 'aria-label', '经历1行动').props.onChange({ target: { value: '整理反馈\n\n' } })
    input(render(), 'type', 'checkbox').props.onChange({ target: { checked: true } })
    expect(props.profile).toMatchObject({ experiences: [{ actions: ['整理反馈'] }], user_confirmed: true })
    button(render(), '根据已确认事实生成简历').props.onClick()
    await settle()
    expect(api.parseResumeText).not.toHaveBeenCalled()
    expect(api.parseResumeFile).not.toHaveBeenCalled()
    expect(props.markdown).toBe('# 虚构同学')
  })
  it('解析失败后可改用手工录入且清除旧错误', async () => {
    props.profile = null; props.sourceText = '待整理材料'
    vi.mocked(api.parseResumeText).mockRejectedValueOnce(new Error('解析服务不可用'))
    button(render(), '整理文本材料').props.onClick(); await settle()
    expect(text(render())).toContain('解析服务不可用')
    button(render(), '直接手工填写事实').props.onClick()
    expect(text(render())).not.toContain('解析服务不可用')
    expect(props.profile).toMatchObject({ user_confirmed: false })
  })
  it('空白经历不能绕过确认处理器，补齐前禁止生成', () => {
    button(render(), '补充一段经历').props.onClick()
    expect(input(render(), 'type', 'checkbox').props.disabled).toBe(true)
    input(render(), 'type', 'checkbox').props.onChange({ target: { checked: true } })
    expect(props.profile?.user_confirmed).toBe(false)
    expect(text(render())).toContain('第 2 段经历')
    button(render(), '根据已确认事实生成简历').props.onClick()
    expect(api.generateResume).not.toHaveBeenCalled()
  })
  it('修正原始材料同步受控文字、撤销确认并保留结构化事实', () => {
    props.markdown = '# 旧稿'; props.sourceName = '旧材料.txt'
    input(render(), 'aria-label', '原始材料').props.onChange({ target: { value: '修正后的虚构材料' } })
    expect(props.sourceText).toBe('修正后的虚构材料')
    expect(props.sourceName).toBe('')
    expect(props.profile).toMatchObject({ raw_text: props.sourceText, user_confirmed: false })
    expect(props.profile?.experiences).toHaveLength(1)
    expect(props.markdown).toBe('')
    expect(input(render(), 'id', 'source-text').props.value).toBe(props.sourceText)
  })
  it('四步导航都指向实际可聚焦区域', () => {
    const tree = render()
    for (let step = 1; step <= 4; step++) {
      expect(input(tree, 'href', `#wb-step-${step}`)).toBeDefined()
      expect(input(tree, 'id', `wb-step-${step}`).props.tabIndex).toBe(-1)
    }
  })
  it.each(['parse', 'generate'])('%s 迟到响应不能覆盖服务器恢复的工作台', async (operation) => {
    let finish!: (value: any) => void
    if (operation === 'parse') {
      props.sourceText = '旧材料'
      vi.mocked(api.parseResumeText).mockImplementationOnce(() => new Promise((resolve) => { finish = resolve }))
      button(render(), '整理文本材料').props.onClick()
    } else {
      vi.mocked(api.generateResume).mockImplementationOnce(() => new Promise((resolve) => { finish = resolve }))
      button(render(), '根据已确认事实生成简历').props.onClick()
    }
    props.sourceText = '恢复的材料'; props.profile = { ...fixture(), name: '服务器版本' }; props.markdown = '# 恢复的简历'
    render()
    finish({ ok: true, profile: fixture(), raw_text: '旧返回', markdown: '# 过期输出' })
    await settle()
    expect(props.profile?.name).toBe('服务器版本')
    expect(props.sourceText).toBe('恢复的材料')
    expect(props.markdown).toBe('# 恢复的简历')
    expect(props.busy).toBe(false)
  })
  it.each(['parse', 'generate'])('%s 正常请求的处理中重渲染不会错误丢弃结果', async (operation) => {
    let finish!: (value: any) => void
    if (operation === 'parse') {
      props.sourceText = '原始材料'
      vi.mocked(api.parseResumeText).mockImplementationOnce(() => new Promise((resolve) => { finish = resolve }))
      button(render(), '整理文本材料').props.onClick()
    } else {
      props.markdown = '# 上一版'
      vi.mocked(api.generateResume).mockImplementationOnce(() => new Promise((resolve) => { finish = resolve }))
      button(render(), '重新生成简历').props.onClick()
    }
    render()
    finish({ ok: true, profile: fixture(), raw_text: '新整理材料', markdown: '# 新稿' })
    await settle()
    if (operation === 'parse') expect(props.sourceText).toBe('新整理材料')
    else expect(props.markdown).toBe('# 新稿')
    expect(props.busy).toBe(false)
  })
  it('使用账户工作台恢复的材料文字与名称', () => {
    props.sourceText = '已保存的虚构材料'
    props.sourceName = '演示材料.txt'
    expect(input(render(), 'id', 'source-text').props.value).toBe('已保存的虚构材料')
    expect(text(render())).toContain('演示材料.txt')
    props.sourceText = '从服务器恢复的新版本'
    expect(input(render(), 'id', 'source-text').props.value).toBe('从服务器恢复的新版本')
  })
  it('输入材料、解析、编辑并确认，再生成', async () => {
    input(render(), 'id', 'source-text').props.onChange({ target: { value: '虚构经历' } })
    expect(props.profile).toBeNull()
    button(render(), '整理文本材料').props.onClick()
    await settle()
    expect(props.profile?.user_confirmed).toBe(false)
    input(render(), 'id', 'person-name').props.onChange({ target: { value: '测试同学' } })
    input(render(), 'type', 'checkbox').props.onChange({ target: { checked: true } })
    button(render(), '根据已确认事实生成简历').props.onClick()
    await settle()
    expect(api.generateResume).toHaveBeenCalledWith('虚构岗位 JD', expect.objectContaining({ name: '测试同学', user_confirmed: true }), [])
    expect(text(render())).toContain('简历已生成')
  })
  it('未确认即使直接调用处理器也不会生成', () => {
    props.profile = { ...fixture(), user_confirmed: false }
    const generate = button(render(), '根据已确认事实生成简历')
    expect(generate.props.disabled).toBe(true)
    generate.props.onClick()
    expect(api.generateResume).not.toHaveBeenCalled()
  })
  it('解析后接入查重预览，事实未确认时禁止导入', () => {
    props.userId='test-account'; props.profile={...fixture(),user_confirmed:false}
    const review=nodes(render()).find(n=>n.type===ImportReview)
    expect(review.props.material.expected_user_id).toBe('test-account')
    expect(review.props.disabled).toBe(true)
    expect(api.saveProfile).not.toHaveBeenCalled()
  })
  it('确认后使用当前材料的独立查重预览，修改材料更换预览', () => {
    props.userId='test-account'
    const first=nodes(render()).find(n=>n.type===ImportReview)
    expect(first.props.disabled).toBe(false)
    input(render(),'aria-label','经历1成果').props.onChange({target:{value:'新的成果'}})
    const second=nodes(render()).find(n=>n.type===ImportReview)
    expect(second.key).not.toBe(first.key)
    expect(second.props.disabled).toBe(true)
    expect(second.props.material.profile.experiences[0].results).toEqual(['新的成果'])
  })
  it('教育卡不显示行动、成果或技能描述输入', () => {
    props.profile={...fixture(),experiences:[{kind:'education',name:'学校',role:'本科',period:'2022—2026',actions:[],results:[],skills:[]}]}
    expect(input(render(),'aria-label','经历1行动')).toBeUndefined()
    expect(input(render(),'aria-label','经历1成果')).toBeUndefined()
    expect(input(render(),'aria-label','经历1技能')).toBeUndefined()
  })
  it.each(['jd', 'fact', 'source'])('修改 %s 会清空旧稿并撤销确认', (kind) => {
    props.markdown = '# 旧稿'
    const tree = render()
    if (kind === 'jd') input(tree, 'id', 'jd-text').props.onChange({ target: { value: '新岗位' } })
    if (kind === 'fact') input(tree, 'id', 'person-name').props.onChange({ target: { value: '新姓名' } })
    if (kind === 'source') input(tree, 'id', 'source-text').props.onChange({ target: { value: '新材料' } })
    expect(props.markdown).toBe('')
    expect(props.profile?.user_confirmed).not.toBe(true)
  })
  it('失败恢复按钮，提供重试且不保留旧稿', async () => {
    props.markdown = '# 旧稿'
    vi.mocked(api.generateResume).mockRejectedValueOnce(new Error('模型生成失败'))
    button(render(), '重新生成简历').props.onClick()
    expect(props.markdown).toBe('')
    expect(props.busy).toBe(true)
    expect(nodes(render()).filter((n) => n.type === 'fieldset').every((n) => n.props.disabled)).toBe(true)
    await settle()
    expect(props.busy).toBe(false)
    expect(text(render())).toContain('模型生成失败')
    button(render(), '重试生成简历').props.onClick()
    await settle()
    expect(props.markdown).toBe('# 虚构同学')
  })
  it('解析无经历不是成功，能重试原文本', async () => {
    vi.mocked(api.parseResumeText).mockResolvedValueOnce({ ok: true, profile: { ...fixture(), experiences: [] } })
    input(render(), 'id', 'source-text').props.onChange({ target: { value: '空洞材料' } })
    button(render(), '整理文本材料').props.onClick()
    await settle()
    expect(props.profile).toBeNull()
    expect(text(render())).toContain('没有识别到经历')
    button(render(), '重试整理材料').props.onClick()
    await settle()
    expect(api.parseResumeText).toHaveBeenLastCalledWith('空洞材料')
    expect(props.profile?.user_confirmed).toBe(false)
  })
  it('拒绝不支持的文件，不向后端上传', () => {
    input(render(), 'type', 'file').props.onChange({ target: { files: [{ name: '材料.gif', size: 10 }], value: '材料.gif' } })
    expect(api.parseResumeFile).not.toHaveBeenCalled()
    expect(api.parseResumeImage).not.toHaveBeenCalled()
    expect(text(render())).toContain('暂不支持此格式')
  })
  it('图片交给视觉解析接口并保留事实确认流程', async () => {
    input(render(), 'type', 'file').props.onChange({ target: { files: [{ name: 'resume.png', size: 10 }], value: 'resume.png' } })
    await settle()
    expect(api.parseResumeImage).toHaveBeenCalled()
    expect(api.parseResumeFile).not.toHaveBeenCalled()
    expect(props.profile?.user_confirmed).toBe(false)
  })
  it('重复点击只发出一个请求，空正文不算成功', async () => {
    vi.mocked(api.generateResume).mockResolvedValueOnce({ ok: true, markdown: ' ' })
    const generate = button(render(), '根据已确认事实生成简历')
    generate.props.onClick(); generate.props.onClick()
    await settle()
    expect(api.generateResume).toHaveBeenCalledTimes(1)
    expect(props.markdown).toBe('')
    expect(text(render())).toContain('未返回简历正文')
  })
  it('HTTP 504 展示中文超时，恢复后可重试', async () => {
    vi.mocked(api.generateResume).mockRejectedValueOnce(new AxiosError('Request failed', undefined, undefined, undefined, {
      status: 504, statusText: '', headers: {}, config: { headers: new AxiosHeaders() }, data: { detail: 'upstream timeout' },
    }))
    button(render(), '根据已确认事实生成简历').props.onClick()
    await settle()
    expect(props.busy).toBe(false)
    expect(text(render())).toContain('处理超时')
    button(render(), '重试生成简历').props.onClick()
    await settle()
    expect(props.markdown).toBe('# 虚构同学')
  })
  it('上传失败后重试原文件，不误用文本材料', async () => {
    const file = { name: '虚构材料.docx', size: 40 }
    vi.mocked(api.parseResumeFile).mockRejectedValueOnce(new Error('上传失败'))
      .mockResolvedValueOnce({ ok: true, profile: fixture() })
    input(render(), 'type', 'file').props.onChange({ target: { files: [file], value: file.name } })
    await settle()
    button(render(), '重试整理材料').props.onClick()
    await settle()
    expect(api.parseResumeFile).toHaveBeenLastCalledWith(file)
    expect(api.parseResumeText).not.toHaveBeenCalled()
    expect(props.profile?.user_confirmed).toBe(false)
  })
  it('手动修改稿件后数字警告不沿用旧检查', async () => {
    vi.mocked(api.generateResume).mockResolvedValueOnce({ ok: true, markdown: '# 虚构同学', untraceable: ['旧数字警告'] })
    button(render(), '根据已确认事实生成简历').props.onClick()
    await settle()
    expect(text(render())).toContain('旧数字警告')
    button(render(), '编辑').props.onClick()
    input(render(), 'aria-label', '编辑简历 Markdown').props.onChange({ target: { value: '# 手动修改稿件' } })
    expect(text(render())).not.toContain('旧数字警告')
    expect(text(render())).toContain('稿件已手动修改')
  })
})

describe('岗位匹配输入保护', () => {
  it.each([
    null,
    { ok: true, coverage: .5, items: [null], missing_hard: [] },
    { ok: true, coverage: 1, items: [{ requirement: '', status: 'covered', evidence: '' }], missing_hard: [] },
    { ok: true, coverage: 80, items: [{ requirement: '需求分析', status: 'covered', evidence: '虚构证据' }], missing_hard: [] },
  ])('异常报告不渲染、不保存且可手动重试 %#', async response => {
    const valid = { ok: true, coverage: 0, items: [{ requirement: 'SQL', status: 'missing', evidence: '', note: '' }], missing_hard: ['SQL'] }
    vi.mocked(api.diagnose).mockResolvedValueOnce(valid as any).mockResolvedValueOnce(response as any).mockResolvedValueOnce({ ...valid, coverage: 1 } as any)
    const done = vi.fn()
    const view = () => { hooks.cursor = 0; return DiagnosePage({ jdText: '岗位', setJdText: vi.fn(), profile: fixture(), onDone: done }) }
    button(view(), '开始诊断').props.onClick(); await settle()
    expect(text(view())).toContain('0%')
    button(view(), '重新诊断').props.onClick()
    expect(text(view())).not.toContain('匹配覆盖率')
    await settle()
    expect(nodes(view()).some(n => n.props?.role === 'alert')).toBe(true)
    expect(text(view())).not.toContain('匹配覆盖率')
    expect(done).toHaveBeenCalledTimes(1)
    expect(button(view(), '重试诊断').props.disabled).toBe(false)
    button(view(), '重试诊断').props.onClick(); await settle()
    expect(text(view())).toContain('100%')
    expect(done).toHaveBeenCalledTimes(2)
    expect(nodes(view()).some(n => n.props?.role === 'alert')).toBe(false)
  })
  it('输入变化后丢弃迟到的旧报告', async () => {
    let finish!: (value: any) => void
    vi.mocked(api.diagnose).mockImplementation(() => new Promise((resolve) => { finish = resolve }))
    const done = vi.fn()
    let jd = '原岗位'
    const view = () => { hooks.cursor = 0; return DiagnosePage({ jdText: jd, setJdText: (value) => { jd = value }, profile: fixture(), onDone: done }) }
    button(view(), '开始诊断').props.onClick()
    jd = '新岗位'; view()
    finish({ ok: true, coverage: 1, items: [{ requirement: '旧要求', status: 'covered' }], missing_hard: [] })
    await settle()
    expect(done).not.toHaveBeenCalled()
    expect(text(view())).not.toContain('旧要求')
  })
})
