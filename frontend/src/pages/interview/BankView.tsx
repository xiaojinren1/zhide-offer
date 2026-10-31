import type { Bank } from './types'

const labels: Record<string, string> = { experience: '经历深挖', professional: '岗位专业能力', behavior: '行为情景', motivation: '求职动机' }
export function BankView({ bank, highlighted }: { bank: Bank; highlighted?: string }) {
  return <div className="space-y-4">{bank.questions.map((q, index) => <article className="panel interview-topic" id={q.id} key={q.id} style={highlighted === q.id ? { outline: '2px solid #3164e0' } : undefined}>
    <span className="section-kicker">{index + 1} / {bank.questions.length} · {labels[q.category] || q.category}</span>
    <h2>{q.question}</h2><p><strong>考察点：</strong>{q.focus}</p>
    <div className="notice"><strong>为什么问你</strong>{q.source_ids.map((id) => {
      const s = bank.sources.find((source) => source.id === id)
      return s ? <p key={id}>{s.kind === 'jd' ? '岗位要求' : s.label}：{s.text}</p> : null
    })}</div>
    <p><strong>可能追问</strong></p><ul>{q.follow_ups.map((f, i) => <li key={i}>{f}</li>)}</ul>
    <details><summary>查看示范回答与回答结构</summary><ol>{q.answer_structure.map((s, i) => <li key={i}>{s}</li>)}</ol>
      <p className="interview-pre">{q.sample_answer}</p><p className="muted">仅摘录已确认事实。请亲自补全真实案例，不能直接把待补充项当成经历。</p>
    </details>
  </article>)}</div>
}
