import { useEffect, useState } from 'react'
import { api, apiErrorMessage } from '../lib/api'
import './model-usage.css'

const number = new Intl.NumberFormat('zh-CN')
const date = new Intl.DateTimeFormat('zh-CN', { dateStyle: 'short', timeStyle: 'medium' })
const tokens = (count: number | null) => count === null ? '—' : number.format(count)
const presets = [
  { label: '今天', days: 1, offset: 0 },
  { label: '昨天', days: 1, offset: 1 },
  { label: '近 7 天', days: 7, offset: 0 },
  { label: '近 30 天', days: 30, offset: 0 },
]

function presetRange(days: number, offset: number) {
  const now = new Date()
  const midnight = (delta: number) =>
    new Date(now.getFullYear(), now.getMonth(), now.getDate() + delta).toISOString()
  return { start: midnight(1 - days - offset), end: midnight(1 - offset) }
}

export default function ModelUsage() {
  const [request, setRequest] = useState<Parameters<typeof api.modelUsage>[0]>({})
  const [selected, setSelected] = useState('全部')
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [report, setReport] = useState<Awaited<ReturnType<typeof api.modelUsage>>>()
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    setBusy(true)
    setError('')
    api.modelUsage(request).then(
      (result) => { if (active) setReport(result) },
      (reason) => { if (active) setError(apiErrorMessage(reason)) },
    ).finally(() => { if (active) setBusy(false) })
    return () => { active = false }
  }, [request])

  const models = report?.models ?? []
  const total = models.reduce((sum, model) => sum + (model.total_tokens ?? 0), 0)
  const unknown = models.reduce((sum, model) => sum + model.unknown_calls, 0)
  const calls = models.reduce((sum, model) => sum + model.calls, 0)

  return <section className="account-section model-usage" aria-labelledby="model-usage-title" aria-busy={busy}>
    <div className="model-usage-header">
      <div className="account-section-title">
        <h3 id="model-usage-title">模型用量</h3>
        <p>查看当前账号在职得内的模型调用。用量以供应商返回为准，时间按本地时区显示。</p>
      </div>
      <button type="button" className="secondary-button" disabled={busy}
        onClick={() => setRequest({ ...request, before: undefined })}>刷新</button>
    </div>
    <div className="model-usage-filters" role="group" aria-label="快捷日期筛选">
      {[{ label: '全部', days: 0, offset: 0 }, ...presets].map(({ label, days, offset }) =>
        <button key={label} type="button" aria-pressed={selected === label}
          className={selected === label ? 'primary-button' : 'secondary-button'}
          onClick={() => {
            setSelected(label)
            setReport(undefined)
            setRequest(days ? presetRange(days, offset) : {})
          }}>{label}</button>
      )}
    </div>
    <form className="model-usage-filters" onSubmit={(event) => {
      event.preventDefault()
      const start = new Date(startDate + 'T00:00:00')
      const end = new Date(endDate + 'T00:00:00')
      end.setDate(end.getDate() + 1)
      setSelected('自定义')
      setReport(undefined)
      setRequest({ start: start.toISOString(), end: end.toISOString() })
    }}>
      <label>开始日期<input type="date" required max={endDate || undefined}
        value={startDate} onChange={(event) => setStartDate(event.target.value)} /></label>
      <label>结束日期<input type="date" required min={startDate || undefined}
        value={endDate} onChange={(event) => setEndDate(event.target.value)} /></label>
      <button type="submit" className={selected === '自定义' ? 'primary-button' : 'secondary-button'}>应用日期</button>
    </form>
    {error && <p className="auth-error" role="alert">{error}</p>}
    {busy && <p role="status">正在读取用量…</p>}
    {!busy && report && !calls && <p>所选日期范围内没有用量记录。</p>}
    {report && calls > 0 && <>
      <dl className="model-usage-summary">
        <div><dt>已知总 Token</dt><dd>{tokens(unknown === calls ? null : total)}</dd></div>
        <div><dt>调用次数</dt><dd>{number.format(calls)}</dd></div>
        <div><dt>总用量未知的调用</dt><dd>{number.format(unknown)}</dd></div>
      </dl>
      <h4>模型用量排行</h4>
      <div className="model-usage-table" tabIndex={0} role="region" aria-label="模型用量排行">
        <table aria-label="按已知总 Token 排序">
          <thead><tr><th scope="col">模型</th><th scope="col">调用次数</th><th scope="col">输入</th><th scope="col">输出</th><th scope="col">总 Token</th></tr></thead>
          <tbody>{models.map((model) => <tr key={model.model}>
            <th scope="row">{model.model}</th><td>{number.format(model.calls)}</td>
            <td>{tokens(model.input_tokens)}</td><td>{tokens(model.output_tokens)}</td><td>{tokens(model.total_tokens)}</td>
          </tr>)}</tbody>
        </table>
      </div>
      <h4>调用明细</h4>
      <div className="model-usage-table" tabIndex={0} role="region" aria-label="模型调用明细">
        <table aria-label="按调用时间倒序">
          <thead><tr><th scope="col">时间</th><th scope="col">模型</th><th scope="col">输入</th><th scope="col">输出</th><th scope="col">总 Token</th></tr></thead>
          <tbody>{report.records.map((record) => <tr key={record.id}>
            <td><time dateTime={record.used_at}>{date.format(new Date(record.used_at))}</time></td>
            <th scope="row">{record.model}</th><td>{tokens(record.input_tokens)}</td>
            <td>{tokens(record.output_tokens)}</td><td>{tokens(record.total_tokens)}</td>
          </tr>)}</tbody>
        </table>
      </div>
      <p className="field-hint">— 表示该项用量未知。排行和合计仅汇总已知用量。</p>
      {report.next_before !== null && <button type="button" className="secondary-button" disabled={busy}
        onClick={() => setRequest({ ...request, before: report.next_before ?? undefined })}>查看更早记录</button>}
    </>}
  </section>
}
