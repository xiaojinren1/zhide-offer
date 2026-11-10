import { useEffect, useState } from 'react'
import { api, apiErrorMessage } from '../lib/api'
import Feedback from './Feedback'
import './admin-dashboard.css'

type Stats = NonNullable<Awaited<ReturnType<typeof api.userStats>>>
type Tab = 'overview' | 'feedback' | 'roles'
const tabs: Array<[Tab, string]> = [['overview', '数据概览'], ['feedback', '反馈管理'], ['roles', '管理员角色']]
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
    {tab === 'feedback' && <Feedback manage />}
    {tab === 'roles' && <Roles username={username} />}
  </div>
}
