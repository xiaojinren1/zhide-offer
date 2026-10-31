export const MAX_ANSWER_LENGTH = 12000
export function answerError(value: string): string | null {
  if (!value.trim()) return '请输入回答，也可以选择跳过。'
  if (value.length > MAX_ANSWER_LENGTH) return `回答最多 ${MAX_ANSWER_LENGTH} 字，请缩减后重试。`
  return null
}
/** 等待模型期间暂停；使用单调时钟，不受系统时间调整影响。 */
export class PracticeClock {
  private accumulated = 0
  private started: number | null = null
  constructor(private now: () => number = () => performance.now()) {}
  resume() { if (this.started === null) this.started = this.now() }
  pause() { if (this.started !== null) { this.accumulated += this.now() - this.started; this.started = null } }
  seconds() { return Math.min(86400, Math.floor((this.accumulated + (this.started === null ? 0 : this.now() - this.started)) / 1000)) }
}
export function formatTime(seconds: number) { return `${Math.floor(seconds / 60).toString().padStart(2, '0')}:${(seconds % 60).toString().padStart(2, '0')}` }
