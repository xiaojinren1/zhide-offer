import { useEffect, useState } from 'react'
import { api, apiErrorMessage } from '../lib/api'
import Feedback from './Feedback'
import { CONTACT_UPDATED_EVENT } from '../components/AdminContact'
import './admin-dashboard.css'

type Stats = NonNullable<Awaited<ReturnType<typeof api.userStats>>>
type Tab = 'overview' | 'errors' | 'feedback' | 'roles' | 'contact'
const tabs: Array<[Tab, string]> = [['overview', '数据概览'], ['errors', '错误趋势'], ['feedback', '反馈管理'], ['roles', '管理员角色'], ['contact', '联系方式']]
const number = new Intl.NumberFormat('zh-CN')

function Trend({ title, days, metric }: { title: string; days: Stats['trend']; metric: 'registrations' | 'tokens' }) {
  const max = Math.max(1, ...days.map(day => day[metric]))
  return <figure className="admin-trend">
    <figcaption>{title}</figcaption>
    <ol aria-label={title}>
      {days.map(day => <li key={day.date} title={`${day.date} · ${number.format(day[metric])}`}>
        <span className="admin-bar-track"><span style={{ height: `${day[metric] / max * 100}%` }} /></span>
        <time dateTime={day.date}>{day.date.slice(5)}</time>
        <span className="visually-hidden">{number.format(day[metric])}</span>
      </li>)}
    </ol>
  </figure>
}

function ErrorTrend() {
  const [days, setDays] = useState(7)
  const [report, setReport] = useState<NonNullable<Awaited<ReturnType<typeof api.errorTrend>>> | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    setLoading(true)
    api.errorTrend({ days, limit: 50 }).then(result => {
      if (active) { setReport(result); setError('') }
    }).catch(reason => { if (active) setError(apiErrorMessage(reason)) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [days])

  const maxDaily = Math.max(1, ...(report?.daily.map(day => day.errors) ?? [1]))
  return <section className="account-section admin-errors">
    <h3>错误趋势</h3>
    <p className="field-hint">
      按事件流（<code>data/events.jsonl</code>）聚合。只展示脱敏的时间、功能、分类和排查编号；
      原始错误文本、材料内容与密钥不会出现在这里。单次尝试失败但已成功切换的不算故障，单独计为「调用重试」。
    </p>
    <label className="admin-errors-window">统计窗口
      <select value={days} onChange={event => setDays(Number(event.target.value))}>
        <option value={1}>近 1 天</option>
        <option value={7}>近 7 天</option>
        <option value={14}>近 14 天</option>
        <option value={30}>近 30 天</option>
      </select>
    </label>
    {error && <p role="alert" className="auth-error">{error}</p>}
    {loading && !report ? <p role="status">正在读取事件流…</p> : report && <>
      <dl className="admin-metrics">
        <div><dt>近 24 小时失败</dt><dd>{number.format(report.totals['24h'])}</dd></div>
        <div><dt>近 {report.window_days} 天失败</dt><dd>{number.format(report.totals.window)}</dd></div>
        <div><dt>调用重试（可能已恢复）</dt><dd>{number.format(report.retries.window)}</dd></div>
        <div><dt>扫描事件数</dt><dd>{number.format(report.events_scanned)}</dd></div>
      </dl>
      {report.totals.window === 0
        ? <p role="status">这个窗口内没有失败事件。</p>
        : <>
          <h4>按分类</h4>
          <table className="admin-table">
            <thead><tr><th scope="col">分类</th><th scope="col">近 24 小时</th>
              <th scope="col">近 {report.window_days} 天</th><th scope="col">排查建议</th></tr></thead>
            <tbody>
              {report.by_category.map(item => <tr key={item.id}>
                <th scope="row">{item.label}</th>
                <td>{number.format(item.last24h)}</td>
                <td>{number.format(item.window)}</td>
                <td className="admin-table-hint">{item.hint}</td>
              </tr>)}
            </tbody>
          </table>
          <h4>按功能入口</h4>
          <table className="admin-table">
            <thead><tr><th scope="col">功能</th><th scope="col">近 24 小时</th>
              <th scope="col">近 {report.window_days} 天</th></tr></thead>
            <tbody>
              {report.by_feature.map(item => <tr key={item.feature}>
                <th scope="row">{item.feature}</th>
                <td>{number.format(item.last24h)}</td>
                <td>{number.format(item.window)}</td>
              </tr>)}
            </tbody>
          </table>
          <h4>每日失败次数</h4>
          <figure className="admin-trend">
            <figcaption>近 {report.window_days} 天</figcaption>
            <ol aria-label="每日失败次数">
              {report.daily.map(day => <li key={day.date} title={`${day.date} · ${number.format(day.errors)}`}>
                <span className="admin-bar-track"><span style={{ height: `${day.errors / maxDaily * 100}%` }} /></span>
                <time dateTime={day.date}>{day.date.slice(5)}</time>
                <span className="visually-hidden">{number.format(day.errors)}</span>
              </li>)}
            </ol>
          </figure>
        </>}
      <h4>最近失败明细</h4>
      {report.recent.length === 0 ? <p className="field-hint">没有可展示的失败记录。</p>
        : <>
          <p className="field-hint">同一条排查编号会合并成一行，"次数"是这一组在窗口内出现的总次数。</p>
          <table className="admin-table">
            <thead><tr><th scope="col">最近一次（北京时间）</th><th scope="col">功能</th>
              <th scope="col">分类</th><th scope="col">次数</th><th scope="col">排查编号</th></tr></thead>
            <tbody>
              {report.recent.map((item, index) => <tr key={`${item.trace_id}-${item.category}-${index}`}>
                <td>{item.time}</td>
                <td>{item.feature}</td>
                <td>{item.category_label}</td>
                <td>{number.format(item.count)}</td>
                <td><code>{item.trace_id}</code></td>
              </tr>)}
            </tbody>
          </table>
        </>}
    </>}
  </section>
}

function Roles({ username }: { username: string }) {
  const [admins, setAdmins] = useState<string[]>([])
  const [target, setTarget] = useState('')
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    api.listAdmins().then(result => { if (active) setAdmins(result.admins) })
      .catch(reason => { if (active) setError(apiErrorMessage(reason)) })
      .finally(() => { if (active) setBusy(false) })
    return () => { active = false }
  }, [])
  async function change(name: string, admin: boolean) {
    if (busy) return
    setBusy(true)
    setError('')
    try {
      await api.changeAdmin(name, admin)
      setAdmins((await api.listAdmins()).admins)
      if (admin) setTarget('')
    } catch (reason) {
      setError(apiErrorMessage(reason))
    } finally {
      setBusy(false)
    }
  }
  return <section className="account-section admin-roles">
    <h3>管理员角色</h3>
    <p>管理员可查看站点统计、处理反馈及管理其他管理员角色。</p>
    <form onSubmit={event => { event.preventDefault(); void change(target.trim(), true) }}>
      <label htmlFor="admin-username">现有账号用户名</label>
      <input id="admin-username" value={target} onChange={event => setTarget(event.target.value)} required maxLength={32} />
      <button className="primary-button" disabled={busy || !target.trim()}>授予管理员角色</button>
    </form>
    {error && <p role="alert" className="auth-error">{error}</p>}
    <ul>{admins.map(name => <li key={name}>
      <strong>{name}</strong>
      {name === username ? <span>当前账号</span> :
        <button type="button" className="secondary-button" disabled={busy} onClick={() => void change(name, false)}>撤销角色</button>}
    </li>)}</ul>
  </section>
}

function ContactSettings() {
  const [qq, setQq] = useState('')
  const [ready, setReady] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    api.contact().then(result => {
      if (active) { setQq(result.qq ?? ''); setReady(true) }
    }).catch(reason => { if (active) setError(apiErrorMessage(reason)) })
    return () => { active = false }
  }, [])
  return <section className="account-section admin-roles">
    <h3>联系方式</h3>
    <p>填写愿意公开的 QQ 号，显示在工作台右上角。留空保存可隐藏入口。</p>
    <form onSubmit={async event => {
      event.preventDefault()
      if (!ready || saving) return
      setSaving(true)
      setSaved(false)
      setError('')
      try {
        await api.updateContact(qq)
        window.dispatchEvent(new Event(CONTACT_UPDATED_EVENT))
        setSaved(true)
      } catch (reason) {
        setError(apiErrorMessage(reason))
      } finally {
        setSaving(false)
      }
    }}>
      <label htmlFor="contact-qq">作者 QQ</label>
      <input id="contact-qq" inputMode="numeric" pattern="[1-9][0-9]{4,11}" maxLength={12}
        disabled={!ready || saving} value={qq} onChange={event => { setQq(event.target.value); setSaved(false) }} />
      <button className="primary-button" disabled={!ready || saving}>保存</button>
    </form>
    {saved && <p role="status">联系方式已保存。</p>}
    {error && <p role="alert" className="auth-error">{error}</p>}
  </section>
}

export default function UserStats({ username }: { username: string }) {
  const [tab, setTab] = useState<Tab>('overview')
  const [stats, setStats] = useState<Stats | null | undefined>()
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    const refresh = () => api.userStats().then(result => {
      if (active) { setStats(result); setError('') }
    }).catch(reason => { if (active) setError(apiErrorMessage(reason)) })
    void refresh()
    const timer = window.setInterval(refresh, 30_000)
    return () => { active = false; window.clearInterval(timer) }
  }, [])

  if (stats === null) return <p role="alert">当前账号没有管理员权限。</p>
  return <div className="account-page admin-dashboard">
    <nav className="model-center-modules" aria-label="管理后台模块">
      {tabs.map(([id, label]) => <button type="button" key={id} aria-pressed={tab === id} onClick={() => setTab(id)}><strong>{label}</strong></button>)}
    </nav>
    {error && <p role="alert" className="auth-error">{error}</p>}
    {tab === 'overview' && (stats ? <>
      <dl className="admin-metrics">
        <div><dt>近 5 分钟在线</dt><dd>{number.format(stats.online)}</dd></div>
        <div><dt>本周新增账号</dt><dd>{number.format(stats.new_this_week)}</dd></div>
        <div><dt>累计注册账号</dt><dd>{number.format(stats.registered)}</dd></div>
      </dl>
      <p className="field-hint">趋势按北京时间统计。Token 仅汇总已记录的已知用量。</p>
      <div className="admin-charts">
        <Trend title="近 14 天新增注册" days={stats.trend} metric="registrations" />
        <Trend title="近 14 天 Token 用量" days={stats.trend} metric="tokens" />
      </div>
    </> : !error && <p role="status">正在读取统计…</p>)}
    {tab === 'errors' && <ErrorTrend />}
    {tab === 'feedback' && <Feedback manage />}
    {tab === 'roles' && <Roles username={username} />}
    {tab === 'contact' && <ContactSettings />}
  </div>
}
