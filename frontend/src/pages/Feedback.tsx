import { useEffect, useState } from 'react'
import { api, apiErrorMessage, type FeedbackStatus } from '../lib/api'
import './feedback.css'

const labels: Record<FeedbackStatus, string> = {
  pending: '待处理',
  reviewing: '处理中',
  resolved: '已处理',
}
const statuses = Object.keys(labels) as FeedbackStatus[]

export default function Feedback({ manage = false }: { manage?: boolean }) {
  const [message, setMessage] = useState('')
  const [query, setQuery] = useState<{ manage: boolean; before?: number }>({ manage })
  const [report, setReport] = useState<Awaited<ReturnType<typeof api.listFeedback>>>()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  useEffect(() => {
    let active = true
    setLoading(true)
    setError('')
    api.listFeedback(query.manage, query.before).then(
      (result) => { if (active) setReport(result) },
      (reason) => { if (active) { setReport(undefined); setError(apiErrorMessage(reason)) } },
    ).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [query])

  async function save(action: () => Promise<unknown>, done: () => void) {
    if (saving) return
    setSaving(true)
    setError('')
    setNotice('')
    try {
      await action()
      done()
    } catch (reason) {
      setError(apiErrorMessage(reason))
    } finally {
      setSaving(false)
    }
  }

  const busy = loading || saving
  return <section className="account-section feedback-panel" aria-labelledby="feedback-title">
    <div className="account-section-title">
      <h3 id="feedback-title">{manage ? '反馈管理' : '站内反馈'}</h3>
      <p>{manage ? '查看用户提交的问题与建议，并更新处理进度。' : '告诉我们你遇到的问题或想要的功能。内容仅本人和管理员可见。'}</p>
    </div>
    {!manage && <form onSubmit={(event) => {
      event.preventDefault()
      if (!message.trim()) return
      void save(() => api.submitFeedback(message.trim()), () => {
        setMessage('')
        setNotice('反馈已提交。')
        setQuery({ manage: false })
      })
    }}>
      <label htmlFor="feedback-message">反馈内容</label>
      <textarea id="feedback-message" rows={4} maxLength={2000} required disabled={saving}
        placeholder="说说你遇到的问题… 请勿填写密码、API Key 或简历隐私信息。"
        value={message} onChange={(event) => setMessage(event.target.value)} />
      <button className="primary-button" disabled={busy || !message.trim()}>提交反馈</button>
    </form>}
    {notice && <p role="status">{notice}</p>}
    {error && <p className="auth-error" role="alert">{error}</p>}
    <div className="feedback-toolbar">
      <h4>{query.manage ? '反馈管理' : '我的反馈'}</h4>
      <button type="button" className="secondary-button" disabled={busy}
        onClick={() => setQuery({ manage: query.manage })}>刷新</button>
    </div>
    {loading && <p role="status">正在读取反馈…</p>}
    {!loading && report && !report.items.length && <p>暂无反馈。</p>}
    {!loading && report?.items.map((item) => <article className="feedback-item" key={item.id}>
      <div className="feedback-toolbar">
        <span className="feedback-avatar" aria-hidden="true">{item.username.slice(0, 1).toUpperCase()}</span>
        <small><strong>{query.manage ? item.username : '我'}</strong>
          <time dateTime={item.created_at}>{new Date(item.created_at).toLocaleString()}</time>
        </small>
        {query.manage ? <select aria-label={`反馈 ${item.id} 的处理状态`} value={item.status} disabled={busy}
          onChange={(event) => {
            const status = event.target.value as FeedbackStatus
            void save(() => api.updateFeedback(item.id, status), () => {
              setNotice('处理状态已更新。')
              setQuery({ ...query })
            })
          }}>{statuses.map((status) => <option value={status} key={status}>{labels[status]}</option>)}</select>
          : <strong className="feedback-status" data-status={item.status}>{labels[item.status]}</strong>}
      </div>
      <p>{item.message}</p>
    </article>)}
    {!loading && report?.next_before != null && <button type="button" className="secondary-button" disabled={busy}
      onClick={() => setQuery({ manage: query.manage, before: report.next_before ?? undefined })}>查看更早反馈</button>}
  </section>
}
