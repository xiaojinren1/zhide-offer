import type { Bank, Citation, Report, Snapshot, Turn } from './types'
import { formatTime } from './practice'

function Evidence({ items }: { items: Citation[] }) {
  return <>{items.map((item, i) => <blockquote key={i}><a href={'#' + item.turn_id}>{item.turn_id.replace('turn-', '回答 ')}：</a>“{item.quote}”</blockquote>)}</>
}
export function ReportView({ report, turns, elapsed, bank, snapshot, onTopic }: { report: Report; turns: Turn[]; elapsed: number; bank: Bank | null; snapshot?: Snapshot | null; onTopic: (id: string) => void }) {
  return <div className="space-y-4">
    <section className="panel"><span className="section-kicker">INTERVIEW REVIEW</span><h2>{report.overall_score === null ? '阶段性反馈 · 暂不提供完整总分' : `整体评价 ${report.overall_score} / 100`}</h2>
      <p>练习用时 {formatTime(elapsed)} · 有效回答 {report.answered_count} 次 · 五个维度等权</p>
      <p>{report.summary}</p>{report.kind === 'partial' && <div className="notice">作答不足或有维度未充分考察，请补充练习后再看完整评价。</div>}
      <p className="muted">评分锚点：0 无法回应；25 空泛；50 有说明但缺细节；75 行动与依据清楚；100 能解释取舍、局限和迁移。未充分考察不计为零分。</p>
      <p className="muted">{report.disclaimer}</p>
    </section>
    <section className="panel"><h2>两个视角的反馈</h2><h3>模拟 HR</h3><p>{report.hr_feedback}</p><h3>岗位面试官</h3><p>{report.interviewer_feedback}</p></section>
    <section className="panel"><h2>五维评价</h2><div className="interview-dimensions">{report.dimensions.map((d) => <article key={d.key}><h3>{d.label} · {d.score === null ? '未充分考察' : `${d.score} 分`}</h3><p>{d.comment}</p><Evidence items={d.evidence} /></article>)}</div></section>
    {([['主要亮点', report.strengths], ['优先改进的三项问题', report.improvements]] as const).map(([title, findings]) => <section className="panel" key={title}><h2>{title}</h2>{findings.length ? findings.map((f, i) => <article key={i}><h3>{i + 1}. {f.title}</h3><p>{f.advice}</p><Evidence items={f.evidence} /></article>) : <p className="muted">当前作答证据不足，暂不推断。</p>}</section>)}
    {report.optimized_answers.length > 0 && <section className="panel"><h2>关键回答如何优化</h2>{report.optimized_answers.map((a, i) => <article key={i}><Evidence items={[{ turn_id: a.turn_id, quote: a.answer_excerpt }]} /><ol>{a.structure.map((s, j) => <li key={j}>{s}</li>)}</ol><p className="interview-pre">{a.example_answer}</p></article>)}</section>}
    <section className="panel"><h2>下一次练习</h2>{report.recommendations.map((r, i) => <p key={i}>{report.coverage.find((c) => c.topic_id === r.topic_id)?.focus}：{r.action} {bank?.questions.some((q) => q.id === r.topic_id) && <button className="secondary-button" onClick={() => onTopic(r.topic_id)}>练习对应主题</button>}</p>)}</section>
    <details className="panel"><summary>本轮考察覆盖情况</summary>{report.coverage.map((c) => <p key={c.topic_id}>{c.focus}：{c.answered ? '已作答' : c.asked ? '提问但未作答' : '未考察'}</p>)}</details>
    <details className="panel"><summary>完整对话与材料快照</summary>{snapshot && <><p>材料冻结于 {snapshot.captured_at}</p><details><summary>本轮简历与 JD</summary><pre>{snapshot.resume_markdown}</pre><pre>{snapshot.jd_text}</pre></details></>}{turns.map((t) => <article key={t.id} id={t.id}><h3>{t.question.text}</h3><p className="interview-pre">{t.skipped ? '【跳过】' : t.answer || '【未作答】'}</p></article>)}</details>
  </div>
}
