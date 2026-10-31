import { useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { OwlLogo, UiIcon } from '../components/Brand'
import { api, apiErrorMessage } from '../lib/api'
import type { AccountUser } from '../lib/api'

export default function AuthPage({ onAuthenticated, notice = '' }: {
  onAuthenticated: (user: AccountUser) => void; notice?: string
}) {
  const [registering, setRegistering] = useState(false)
  const [forgotPassword, setForgotPassword] = useState(false)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const submitting = useRef(false)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (submitting.current) return
    setError('')
    if (!/^[A-Za-z0-9_]{3,32}$/.test(username)) {
      setError('用户名请使用 3–32 位英文字母、数字或下划线。'); return
    }
    if (password.length < 8 || password.length > 128) {
      setError('密码长度应为 8–128 个字符。'); return
    }
    if (registering && password !== confirmation) {
      setError('两次输入的密码不一致。'); return
    }
    submitting.current = true
    setBusy(true)
    try {
      const result = await (registering ? api.register(username, password) : api.login(username, password))
      onAuthenticated(result.user)
    } catch (reason) {
      setError(apiErrorMessage(reason))
    } finally {
      submitting.current = false
      setBusy(false)
    }
  }

  if (forgotPassword) {
    return <main className="auth-shell">
      <div className="auth-layout">
        <section className="auth-intro">
          <div className="brand"><OwlLogo /><span>职得<span className="brand-offer">offer</span></span></div>
          <span className="eyebrow">ACCOUNT RECOVERY</span>
          <h1>找回你的<br />求职空间。</h1>
          <p>账户资料和求职材料都属于个人空间，恢复操作需要经过管理员核验。</p>
          <div className="auth-promise"><UiIcon name="shield" /><span>不会仅凭用户名直接修改密码</span></div>
        </section>
        <section className="auth-card" aria-labelledby="auth-title">
          <span className="section-kicker">PASSWORD RECOVERY</span>
          <h2 id="auth-title">忘记密码</h2>
          <p className="auth-description">当前账户还没有绑定邮箱、手机号或恢复码。请联系团队管理员核验身份并重置密码。</p>
          <p className="auth-notice" role="status">为保护账户安全，输入用户名不会直接修改密码，也不会暴露账户是否存在。</p>
          <button type="button" className="primary-button full auth-submit" onClick={() => { setForgotPassword(false); setError('') }}>返回登录</button>
          <p className="auth-switch">还没有账户？<button type="button" onClick={() => { setForgotPassword(false); setRegistering(true); setError('') }}>创建账户</button></p>
        </section>
      </div>
      <footer className="auth-footer">职得offer · 让每一段真实经历被看见</footer>
    </main>
  }

  return <main className="auth-shell">
    <div className="auth-layout">
      <section className="auth-intro">
        <div className="brand"><OwlLogo /><span>职得<span className="brand-offer">offer</span></span></div>
        <span className="eyebrow">YOUR NEXT CHAPTER</span>
        <h1>你的每一段经历，<br />都值得被看见。</h1>
        <p>从真实经历出发，为心仪岗位整理简历，<br className="auth-desktop-break" />也为下一次面试做好准备。</p>
        <div className="auth-promise"><UiIcon name="shield" /><span>自己的账户，自己的求职空间</span></div>
      </section>
      <section className="auth-card" aria-labelledby="auth-title">
        <span className="section-kicker">{registering ? 'START YOUR JOURNEY' : 'WELCOME BACK'}</span>
        <h2 id="auth-title">{registering ? '创建你的账户' : '登录职得offer'}</h2>
        <p className="auth-description">{registering ? '注册后即可进入工作台，开始准备下一份机会。' : '欢迎回来，继续为下一份机会做准备。'}</p>
        {notice && <p className="auth-notice" role="status">{notice}</p>}
        <form onSubmit={submit}>
          <fieldset disabled={busy}>
            <label htmlFor="account-username">用户名</label>
            <input id="account-username" name="username" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required minLength={3} maxLength={32} pattern="[A-Za-z0-9_]{3,32}" spellCheck={false} placeholder="例如 zhide_team" aria-describedby="username-help" />
            <p id="username-help" className="auth-field-hint">3–32 位英文字母、数字或下划线，大小写不敏感</p>
            <label htmlFor="account-password">密码</label>
            <input id="account-password" name="password" type="password" autoComplete={registering ? 'new-password' : 'current-password'} value={password} onChange={(e) => setPassword(e.target.value)} required minLength={8} maxLength={128} placeholder="输入 8–128 个字符" />
            {registering && <><label htmlFor="account-confirmation">确认密码</label><input id="account-confirmation" name="confirmation" type="password" autoComplete="new-password" value={confirmation} onChange={(e) => setConfirmation(e.target.value)} required minLength={8} maxLength={128} placeholder="再次输入密码" /></>}
            {error && <p className="auth-error" role="alert">{error}</p>}
            <button className="primary-button full auth-submit" type="submit">{busy ? '正在处理…' : registering ? '创建账户并进入 →' : '登录并进入工作台 →'}</button>
          </fieldset>
        </form>
        <p className="auth-switch">{registering ? '已有账户？' : '第一次使用？'}<button type="button" disabled={busy} onClick={() => { setRegistering(!registering); setPassword(''); setConfirmation(''); setError('') }}>{registering ? '直接登录' : '创建账户'}</button></p>
        {!registering && <p className="auth-switch auth-recovery-link"><button type="button" disabled={busy} onClick={() => { setForgotPassword(true); setError('') }}>忘记密码？</button></p>}
        <p className="auth-retention">登录状态可保留 7 天。工作台自动保存至当前账户，离开前请确认已保存。</p>
      </section>
    </div>
    <footer className="auth-footer">职得offer · 让每一段真实经历被看见</footer>
  </main>
}
