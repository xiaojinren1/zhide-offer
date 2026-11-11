/// <reference types="vitest" />
import { describe, expect, it } from 'vitest'
import { diffLines, diffSummary } from './textDiff'

describe('diffLines', () => {
  it('相同文本没有变化', () => {
    const lines = diffLines('第一行\n第二行', '第一行\n第二行')
    expect(lines.every(line => line.type === 'same')).toBe(true)
    expect(diffSummary(lines)).toEqual({ added: 0, removed: 0 })
  })

  it('能看出新增和删除的行', () => {
    const lines = diffLines('一面问了项目\n二面问了算法', '一面问了项目\n二面问了算法与手写 LRU')
    expect(diffSummary(lines)).toEqual({ added: 1, removed: 1 })
    expect(lines.filter(line => line.type === 'same').map(line => line.text)).toEqual(['一面问了项目'])
  })

  it('整段替换时保留未变的前缀', () => {
    const lines = diffLines('标题\nA\nB', '标题\nC\nD')
    expect(lines[0]).toEqual({ type: 'same', text: '标题' })
    expect(diffSummary(lines)).toEqual({ added: 2, removed: 2 })
  })

  it('旧版为空时全是新增', () => {
    const lines = diffLines('', '新内容第一行\n新内容第二行')
    expect(diffSummary(lines).added).toBeGreaterThanOrEqual(2)
  })
})
