import { describe, expect, it } from 'vitest'
import { validateDiagnosis } from './diagnose'

const row = () => ({ requirement: '需求分析', status: 'covered', evidence: '虚构项目：整理需求', note: '' })
const report = () => ({ ok: true, coverage: .5, items: [row()], missing_hard: [] })

describe('匹配报告运行时校验', () => {
  it.each([null, undefined, [], 'report', {}, { ok: false, error: {} }])('拒绝非法响应 %#', value => {
    expect(() => validateDiagnosis(value)).toThrow()
  })
  it('保留服务端文字错误', () => {
    expect(() => validateDiagnosis({ ok: false, error: '模型超时' })).toThrow('模型超时')
  })
  it.each([-1, 1.01, 80, NaN, Infinity, '0.5', null, undefined])('拒绝覆盖率 %s', coverage => {
    expect(() => validateDiagnosis({ ...report(), coverage })).toThrow()
  })
  it.each([0, 1])('允许边界覆盖率 %s', coverage => {
    expect(validateDiagnosis({ ...report(), coverage }).coverage).toBe(coverage)
  })
  it.each([null, [], [null], [{}], [{ ...row(), requirement: ' ' }], [{ ...row(), requirement: {} }],
    [{ ...row(), status: 'unknown' }], [{ ...row(), evidence: '' }], [{ ...row(), evidence: undefined }],
    [{ ...row(), status: 'partial', evidence: ' ' }], [{ ...row(), evidence: {} }], [{ ...row(), note: [] }],
    [row(), null]])('拒绝不完整条目 %#', items => {
    expect(() => validateDiagnosis({ ...report(), items })).toThrow()
  })
  it.each([null, {}, [null], [' '], [7]])('拒绝非文本缺失列表 %#', missing_hard => {
    expect(() => validateDiagnosis({ ...report(), missing_hard })).toThrow()
  })
  it.each([{ job_title: {} }, { jd: null }, { jd: { keywords: {} } }, { jd: { keywords: [null] } },
    { missing_hard_count: -1 }, { missing_hard_count: 1.5 }, { missing_hard_count: 1 }])('拒绝非法展示或持久化字段 %#', fields => {
    expect(() => validateDiagnosis({ ...report(), ...fields })).toThrow()
  })
  it('允许缺失项没有证据及可选文字缺省，归一化安全文本', () => {
    const result = validateDiagnosis({ ...report(), items: [{ requirement: ' SQL ', status: 'missing' }],
      missing_hard: [' SQL '], missing_hard_count: 1, jd: { keywords: [' SQL '] } })
    expect(result).toMatchObject({ job_title: '', keywords: ['SQL'], missing_hard: ['SQL'], missing_hard_count: 1,
      items: [{ requirement: 'SQL', status: 'missing', evidence: '', note: '' }] })
  })
  it('缺省 JD 关键词不会进入父级异常数据', () => {
    expect(validateDiagnosis(report()).keywords).toEqual([])
    expect(validateDiagnosis({ ...report(), jd: {} }).keywords).toEqual([])
  })
})
