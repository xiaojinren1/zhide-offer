import { describe, expect, it } from 'vitest'
import { answerError, formatTime, PracticeClock } from './practice'
import { isBank, isReport, isSession } from './types'
import { bankFixture, reportFixture, sessionFixture } from './test-support'

describe('interview clock and response boundaries', () => {
  it('excludes model waiting time and permits practice beyond fifteen minutes', () => {
    let now = 0; const clock = new PracticeClock(() => now)
    clock.resume(); now = 895000; clock.pause(); now += 90000
    expect(clock.seconds()).toBe(895)
    clock.resume(); now += 20000
    expect(clock.seconds()).toBe(915)
    expect(formatTime(clock.seconds())).toBe('15:15')
  })
  it('validates answer boundaries without keyword scoring', () => {
    expect(answerError('  ')).toContain('请输入')
    expect(answerError('我不知道')).toBeNull()
    expect(answerError('答'.repeat(12000))).toBeNull()
    expect(answerError('答'.repeat(12001))).toContain('12000')
  })
  it('rejects malformed nested values that would crash React rendering', () => {
    expect(isBank(bankFixture())).toBe(true)
    expect(isSession(sessionFixture())).toBe(true)
    expect(isReport(reportFixture().report)).toBe(true)
    const broken = reportFixture().report
    broken.dimensions[0].comment = { error: 'private' } as unknown as string
    expect(isReport(broken)).toBe(false)
    const bank = bankFixture(); bank.questions[0].follow_ups = [{} as string]
    expect(isBank(bank)).toBe(false)
  })
})
