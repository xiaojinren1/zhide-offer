import { describe, expect, it } from 'vitest'
import type { ResumeProfile } from './types'
import { tailoringReport, type TailoringReport } from './tailoring'

const profile: ResumeProfile = { name: '虚构同学', user_confirmed: true, skills: ['SQL'], education: ['虚构大学 本科'],
  experiences: [{ kind: 'project', name: '数据练习', role: '', period: '', actions: ['使用 SQL 分析订单'], results: [], skills: ['SQL'] },
    { kind: 'project', name: '校园项目', role: '', period: '', actions: ['绘制原型'], results: [], skills: [] }] }
const jd = '使用 SQL 分析；熟悉 Java；绘制原型'
const markdown = '# 虚构同学\n使用 SQL 分析订单'
const report = (): TailoringReport => ({ version: 1, selected_experiences: [{ id: 'e1', name: '数据练习' }],
  requirements: [{ id: 'r1', requirement: '使用 SQL 分析', priority: 'core', status: 'supported',
    evidence: [{ id: 'e1.actions.1', text: '使用 SQL 分析订单', experience_id: 'e1', experience_name: '数据练习', field: 'actions' }], output_excerpt: '使用 SQL 分析订单' },
  { id: 'r2', requirement: '熟悉 Java', priority: 'core', status: 'gap', evidence: [], output_excerpt: '' },
  { id: 'r3', requirement: '绘制原型', priority: 'support', status: 'omitted',
    evidence: [{ id: 'e2.actions.1', text: '绘制原型', experience_id: 'e2', experience_name: '校园项目', field: 'actions' }], output_excerpt: '' }],
  unsupported_claims: [], review_note: '模型复核不是事实认证。' })

describe('岗位定制报告边界', () => {
  it('拒绝遗漏核心条目或只引用片段的报告', () => {
    const value = report(); value.requirements.splice(1, 1)
    expect(tailoringReport(value, profile, jd, markdown)).toBeNull()
    const partial = report(); partial.requirements[0].requirement = 'SQL'
    expect(tailoringReport(partial, profile, jd, markdown)).toBeNull()
  })
  it('姓名或无关原句不能作为体现岗位的摘录', () => {
    const value = report(); value.requirements[0].output_excerpt = '虚构同学'
    expect(tailoringReport(value, profile, jd, markdown)).toBeNull()
  })
  it('SQL 事实不能仅通过 NoSQL 中的子串建立证据关联', () => {
    const value = report(); value.requirements[0].output_excerpt = 'NoSQL'
    expect(tailoringReport(value, profile, jd, '# 虚构同学\nNoSQL')).toBeNull()
  })
  it('原文条目切分兼容中英文标点、换行与重复项', () => {
    expect(tailoringReport(report(), profile, '使用 SQL 分析,熟悉 Java。\n绘制原型；使用 SQL 分析', markdown)).not.toBeNull()
  })
  it('拒绝越界修订次数，接受已修订报告', () => {
    expect(tailoringReport({ ...report(), revision_count: 1 }, profile, jd, markdown)).not.toBeNull()
    expect(tailoringReport({ ...report(), revision_count: 2 }, profile, jd, markdown)).toBeNull()
  })
  it('接受当前 JD、事实和稿件一致的报告，保留缺口', () => {
    expect(tailoringReport(report(), profile, jd, markdown)).toEqual(report())
  })
  it.each([null, undefined, {}, [], { ...report(), version: 2 }, { ...report(), requirements: [] }, { ...report(), selected_experiences: [] }])('缺失/非法报告不当作成功：%j', value => {
    expect(tailoringReport(value, profile, jd, markdown)).toBeNull()
  })
  it.each(['要求原文', '证据原文', '证据编号', '所属经历', '字段', '正文摘录', '缺口摘录', '重复要求', '重复证据', '假支持', '状态', '优先级'])('拒绝异常字段：%s', kind => {
    const value = report() as any
    const row = value.requirements[0], fact = row.evidence[0]
    if (kind === '要求原文') row.requirement = '管理团队'
    if (kind === '证据原文') fact.text = '领导团队开发'
    if (kind === '证据编号') fact.id = 'e999.actions.1'
    if (kind === '所属经历') fact.experience_name = '其他项目'
    if (kind === '字段') fact.field = 'skills'
    if (kind === '正文摘录') row.output_excerpt = '正文没有这段'
    if (kind === '缺口摘录') value.requirements[1].output_excerpt = '使用 SQL 分析订单'
    if (kind === '重复要求') value.requirements.push(row)
    if (kind === '重复证据') row.evidence.push(fact)
    if (kind === '假支持') value.requirements[1].status = 'supported'
    if (kind === '状态') row.status = 'perfect'
    if (kind === '优先级') row.priority = 'perfect'
    expect(tailoringReport(value, profile, jd, markdown)).toBeNull()
  })
  it('已选经历必须存在且名称对应，不能重复', () => {
    for (const selected of [[{ id: 'e0', name: '数据练习' }], [{ id: 'e1', name: '其他项目' }], [report().selected_experiences[0], report().selected_experiences[0]]]) {
      expect(tailoringReport({ ...report(), selected_experiences: selected }, profile, jd, markdown)).toBeNull()
    }
  })
  it('报告可以指出有事实但正文未体现，不能假装满足', () => {
    const value = report(); value.requirements[0].output_excerpt = ''
    expect(tailoringReport(value, profile, jd, markdown)?.requirements[0].output_excerpt).toBe('')
  })
  it('未选经历只能显示 omitted，不能显示 supported', () => {
    const value = report()
    expect(tailoringReport(value, profile, jd, markdown)).not.toBeNull()
    value.requirements[2].status = 'supported'
    expect(tailoringReport(value, profile, jd, markdown)).toBeNull()
  })
  it('超出事实的待核对表述必须有真实正文原句', () => {
    const value = report(); value.unsupported_claims = [{ quote: '使用 SQL 分析订单', reason: '需核对' }]
    expect(tailoringReport(value, profile, jd, markdown)).not.toBeNull()
    value.unsupported_claims[0].quote = '不存在的内容'
    expect(tailoringReport(value, profile, jd, markdown)).toBeNull()
  })
  it('事实、JD 或正文变化后旧报告失效', () => {
    expect(tailoringReport(report(), profile, '其他岗位', markdown)).toBeNull()
    expect(tailoringReport(report(), profile, jd, '# 恢复稿')).toBeNull()
    expect(tailoringReport(report(), { ...profile, experiences: [] }, jd, markdown)).toBeNull()
  })
  it('支持个人技能和教育事实，但不能从个人资料虚构行动', () => {
    const value = report()
    value.requirements[0].evidence = [{ id: 'profile.skills.1', text: 'SQL', experience_id: '', experience_name: '个人资料', field: 'skills' }]
    expect(tailoringReport(value, profile, jd, markdown)).not.toBeNull()
    value.requirements[0].evidence[0] = { id: 'profile.actions.1', text: 'SQL', experience_id: '', experience_name: '个人资料', field: 'actions' }
    expect(tailoringReport(value, profile, jd, markdown)).toBeNull()
  })
})
