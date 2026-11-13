import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { api, apiErrorMessage } from '../lib/api'
import type { AccountUser } from '../lib/api'
import UserStats from './UserStats'
import { OwlLogo } from '../components/Brand'
import './admin-console.css'

/**
 * 管理端独立入口（`/admin`）。
 *
 * 为什么单独做一页而不是在用户端加个链接：
 * - 公开站点上，"谁先注册谁是管理员"等于把后台交给运气，所以管理员只能由运维用
 *   `backend/manage.py admin create` 创建；这里只负责**登录并校验角色**。
 * - 用户端与管理员端分开，普通人打开 `/admin` 只会看到"仅管理员可访问"，不会误入管理界面。
 */
export default function AdminConsole() {
  const [user, setUser] = useState<AccountUser | null>(null)
  const [checking, setChecking] = useState(true)
  const [isAdmin, setIsAdmin] = useState(false)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function inspect() {
    setChecking(true)
    try {
      const me = await api.me()
      setUser(me.user)
      const stats = await api.userStats()
      setIsAdmin(Boolean(stats))
    } catch {
      setUser(null)
      setIsAdmin(false)
    } finally {
      setChecking(false)
    }
  }

  useEffect(() => { void inspect() }, [])

  async function login(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy) return
    setBusy(true)
    setError('')
    try {
      await api.login(username.trim(), password)
      setPassword('')
      await inspect()
    } catch (reason) {
      setError(apiErrorMessage(reason))
    } finally {
      setBusy(false)
    }
  }

  async function logout() {
    if (busy) return
    setBusy(true)
    try {
      await api.logout()
    } catch {
      /* 退出失败也把本地状态清掉，用户可刷新重试 */
    } finally {
      setBusy(false)
      setUser(null)
      setIsAdmin(false)
    }
  }

  return <main className="admin-console">
    <header className="admin-console-top">
      <a className="admin-console-brand" href="/">
        <OwlLogo /><span>职得<span className="brand-offer">offer</span></span>
      </a>
      <span className="admin-console-tag">管理端</span>
      <div className="admin-console-actions">
        <a className="secondary-button" href="/">返回用户端</a>
        {user && <button type="button" className="secondary-button" disabled={busy} onClick={() => void logout()}>退出登录</button>}
      </div>
    </header>

    <section className="admin-console-body">
      {checking ? <p role="status">正在确认登录状态…</p>
        : !user ? <>
          <h1>管理员登录</h1>
          <p className="field-hint">
            管理端与用户端分开：这里只接受已授予管理员角色的账号。
            如果站点还没有管理员，请在服务器上执行
            <code> .venv/bin/python backend/manage.py admin create 用户名</code> 创建。
          </p>
          <form className="admin-console-form" onSubmit={login}>
            <label htmlFor="admin-username">用户名</label>
            <input id="admin-username" value={username} autoComplete="username" required maxLength={32}
              onChange={event => setUsername(event.target.value)} />
            <label htmlFor="admin-password">密码</label>
            <input id="admin-password" type="password" value={password} autoComplete="current-password"
              required maxLength={128} onChange={event => setPassword(event.target.value)} />
            {error && <p role="alert" className="auth-error">{error}</p>}
            <button className="primary-button" disabled={busy}>{busy ? '登录中…' : '登录管理端'}</button>
          </form>
        </> : !isAdmin ? <>
          <h1>仅管理员可访问</h1>
          <p>
            当前账号 <strong>{user.username}</strong> 没有管理员权限。
            管理员角色只能由运维在服务器上授予（<code>backend/manage.py admin grant 用户名</code>），
            公开注册的账号一律是普通用户。
          </p>
          <div className="admin-console-actions">
            <a className="primary-button" href="/">返回用户端</a>
            <button type="button" className="secondary-button" disabled={busy} onClick={() => void logout()}>换个账号登录</button>
          </div>
        </> : <>
          <div className="admin-console-heading">
            <h1>管理后台</h1>
            <span className="field-hint">当前账号：{user.username}</span>
          </div>
          <UserStats username={user.username} />
        </>}
    </section>
  </main>
}
