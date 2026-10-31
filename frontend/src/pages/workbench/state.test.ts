import { describe, expect, it } from 'vitest'
import { AxiosError, AxiosHeaders } from 'axios'
import type { ResumeProfile } from '../../lib/types'
import { changedFacts, confirmedProfile, emptyExperience, factIssues, fileError, generatedMarkdown, generationBlock, manualProfile, MAX_FILE_BYTES, operationError, parsedProfile, progress } from './state'

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
  it('拒绝不支持、空文件和超大文件', () => {
    expect(fileError({ name: '材料.png', size: 1 })).toContain('暂不支持')
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
