import { describe, expect, it } from 'vitest'
import { AxiosError, AxiosHeaders } from 'axios'
import type { ResumeProfile } from '../../lib/types'
import { changedFacts, confirmedProfile, emptyExperience, factIssues, fileError, generatedMarkdown, generationBlock, generationReview, manualProfile, MAX_FILE_BYTES, operationError, parsedProfile, progress } from './state'

const profile: ResumeProfile = { name: '虚构同学', experiences: [{ kind: 'project', name: '校园项目', role: '成员', period: '2025.03—2025.06', actions: ['整理需求'], results: ['完成文档'], skills: ['需求分析'] }], skills: [], education: [], user_confirmed: true }

describe('工作台状态与输入', () => {
  it('手工录入保留材料且不伪装确认或 AI 解析', () => {
    const manual = manualProfile('虚构材料')
    expect(manual.raw_text).toBe('虚构材料')
    expect(manual.user_confirmed).toBe(false)
    expect(manual.experiences).toEqual([emptyExperience()])
    expect(factIssues(manual)).toHaveLength(2)
    expect(() => confirmedProfile(manual)).toThrow('经历名称')
  })
  it('空名称、全空白行动或成果即使标记已确认也阻止生成', () => {
    const empty = { ...profile, experiences: [{ ...emptyExperience(), actions: [' ', '\n'], results: [''] }] }
    expect(generationBlock(empty, '岗位')).toContain('经历名称')
    expect(progress(empty, '岗位', '# 旧稿').step).toBe(2)
    expect(() => confirmedProfile(empty)).toThrow('行动或真实成果')
  })
  it('每一段经历都需补齐，但不要求编造数字或时间', () => {
    expect(factIssues({ ...profile, experiences: [...profile.experiences, emptyExperience()] })[0]).toContain('第 2 段')
    const minimal = { ...profile, name: '', experiences: [{ ...emptyExperience(), name: '真实校园活动', results: ['整理反馈'] }] }
    expect(factIssues(minimal)).toEqual([])
    expect(confirmedProfile(minimal).experiences[0].period).toBe('')
  })
  it('确认清理空行，保留扩展追溯字段，不修改输入对象', () => {
    const source = { ...profile, skills: [' ', ' 协作 '], experiences: [{ ...profile.experiences[0], name: ' 项目 ', source_text: '原文依据', actions: [' 行动 ', ''] }] }
    const result = confirmedProfile(source)
    expect(result.skills).toEqual(['协作'])
    expect(result.experiences[0]).toMatchObject({ name: '项目', source_text: '原文依据', actions: ['行动'] })
    expect(source.experiences[0].actions).toEqual([' 行动 ', ''])
  })
  it('教育经历无行动和成果也可确认，不删除教育或编造内容', () => {
    const education = { ...emptyExperience(), kind: 'education', name: '虚构大学', role: '本科' }
    const source = { ...profile, user_confirmed: false, education: ['虚构大学 本科'], experiences: [education, ...profile.experiences] }
    expect(factIssues(source)).toEqual([])
    const confirmed = confirmedProfile(source)
    expect(confirmed.experiences[0]).toEqual(education)
    expect(confirmed.education).toEqual([])
    expect(source.education).toEqual(['虚构大学 本科'])
    expect(generationBlock(confirmed, '岗位')).toBe('')
    expect(factIssues({ ...source, experiences: [{ ...education, name: ' ' }] })).toEqual(['第 1 段经历：请填写经历名称。'])
  })
  it.each(['project', 'internship', 'work', 'unknown'])('%s 经历仍必须有真实行动或成果', (kind) => {
    expect(factIssues({ ...profile, experiences: [{ ...emptyExperience(), kind, name: '虚构经历' }] })).toEqual(['第 1 段经历：请至少填写一项行动或真实成果。'])
  })
  it('按四步显示进度', () => {
    expect(progress(null, '', '').step).toBe(1)
    expect(progress(changedFacts(profile), '岗位', '').step).toBe(2)
    expect(progress(profile, '', '').step).toBe(3)
    expect(progress(profile, '岗位', '').step).toBe(4)
    expect(progress(profile, '岗位', '# 简历').label).toBe('已生成')
  })
  it('未确认、没有经历或 JD 为空均不能生成', () => {
    expect(generationBlock(changedFacts(profile), '岗位')).toContain('确认')
    expect(generationBlock({ ...profile, experiences: [] }, '岗位')).toContain('尚无经历')
    expect(generationBlock(profile, '  ')).toContain('JD')
    expect(generationBlock(profile, '岗位')).toBe('')
  })
  it('修改事实撤销确认且不修改原始对象', () => {
    expect(changedFacts(profile).user_confirmed).toBe(false)
    expect(profile.user_confirmed).toBe(true)
  })
  it.each(['TXT', 'md', 'docx', 'pdf'])('接受 %s', (ext) => {
    expect(fileError({ name: `材料.${ext}`, size: 10 })).toBe('')
  })
  it.each(['png', 'jpg', 'jpeg', 'webp'])('接受图片 %s', (ext) => {
    expect(fileError({ name: `材料.${ext}`, size: 10 })).toBe('')
  })
  it('拒绝不支持、空文件和超大文件', () => {
    expect(fileError({ name: '材料.gif', size: 1 })).toContain('暂不支持')
    expect(fileError({ name: '材料.doc', size: 1 })).toContain('暂不支持')
    expect(fileError({ name: '材料.txt', size: 0 })).toContain('为空')
    expect(fileError({ name: '材料.pdf', size: MAX_FILE_BYTES + 1 })).toContain('10 MB')
    expect(fileError({ name: '材料.pdf', size: MAX_FILE_BYTES })).toBe('')
  })
  it('解析成功后仍需重新确认', () => {
    expect(parsedProfile({ ok: true, profile }).user_confirmed).toBe(false)
  })
  it('解析空结果、空经历和业务错误不能显示成功', () => {
    expect(() => parsedProfile({ ok: true })).toThrow('解析结果')
    expect(() => parsedProfile({ ok: true, profile: { ...profile, experiences: [] } })).toThrow('没有识别到经历')
    expect(() => parsedProfile({ ok: false, error: '解析失败' })).toThrow('解析失败')
    expect(() => parsedProfile({ ok: true, profile: { ...profile, experiences: [{ ...profile.experiences[0], actions: null }] } as unknown as ResumeProfile })).toThrow('结构不完整')
    expect(() => parsedProfile({ ok: true, profile: { ...profile, education: '不是数组' } as unknown as ResumeProfile })).toThrow('结构不完整')
  })
  it('空正文与失败结果不能显示生成成功', () => {
    expect(() => generatedMarkdown({ ok: true, markdown: ' \n' })).toThrow('简历正文')
    expect(() => generatedMarkdown({ ok: false, error: '生成失败' })).toThrow('生成失败')
    expect(generatedMarkdown({ ok: true, markdown: '# 虚构同学' })).toBe('# 虚构同学')
    expect(() => generatedMarkdown({ ok: true, markdown: {} as string })).toThrow('简历正文')
  })
})

describe('生成稿质检提示', () => {
  const clean = { self_check: { passed: true, issues_remaining: 0, high_remaining: 0 }, traceability_passed: true }
  it('读取真实联调中的未通过状态和数量', () => {
    const review = generationReview({ self_check: { passed: false, issues_remaining: 5, high_remaining: 1 }, traceability_passed: true })
    expect(review.warning).toBe(true)
    expect(review.title).toContain('质检未通过')
    expect(review.detail).toContain('剩余 5 项问题，其中高风险 1 项')
  })
  it('矛盾的 passed=true 不能掩盖高风险或剩余问题', () => {
    expect(generationReview({ ...clean, self_check: { passed: true, issues_remaining: 2, high_remaining: 1 } }).title).toContain('未通过')
    expect(generationReview({ ...clean, self_check: { passed: true, issues_remaining: 2, high_remaining: 0 } }).warning).toBe(true)
  })
  it.each([null, {}, { self_check: 'invalid' }, { self_check: { passed: 'true' } },
    { ...clean, self_check: { passed: true, issues_remaining: -1, high_remaining: 0 } },
    { ...clean, self_check: { passed: true, issues_remaining: 0, high_remaining: '0' } },
    { ...clean, self_check: { passed: true, issues_remaining: NaN, high_remaining: 0 } },
    { self_check: clean.self_check },
  ])('缺失或异常元数据不伪装通过：%j', (value) => {
    expect(generationReview(value)).toMatchObject({ warning: true, title: '质检状态未知 · 草稿待核对' })
  })
  it('未通过标记在缺失数量时仍然显示', () => {
    expect(generationReview({ self_check: { passed: false } }).detail).toContain('质检未通过')
  })
  it('数字追溯失败或存在警告时独立提示', () => {
    expect(generationReview({ ...clean, traceability_passed: false }).detail).toContain('数字追溯检查未通过')
    expect(generationReview({ ...clean, untraceable: ['无依据的数字'] }).warning).toBe(true)
  })
  it('自动检查无问题也不等于事实认证', () => {
    expect(generationReview(clean)).toMatchObject({ warning: false })
    expect(generationReview(clean).detail).toContain('不代表事实已被认证')
  })
})

function httpError(status: number, data = {}) {
  return new AxiosError('request failed', undefined, undefined, undefined, { status, statusText: '', headers: {}, config: { headers: new AxiosHeaders() }, data })
}

describe('中文失败提示', () => {
  it.each([401, 422, 429, 503, 504])('HTTP %i 不暴露原始 Axios 错误', (status) => {
    expect(operationError(httpError(status))).not.toContain('request failed')
  })
  it('保留服务端 detail 和 error 字符串', () => {
    expect(operationError(httpError(503, { detail: '请配置模型密钥' }))).toBe('请配置模型密钥')
    expect(operationError(httpError(400, { error: '材料格式错误' }))).toBe('材料格式错误')
  })
  it('正确区分网络和客户端超时', () => {
    expect(operationError(new AxiosError('timeout', 'ECONNABORTED'))).toContain('超时')
    expect(operationError(new AxiosError('network', 'ERR_NETWORK'))).toContain('无法连接')
  })
})
