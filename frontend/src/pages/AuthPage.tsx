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
  const [recoveryUsername, setRecoveryUsername] = useState('')
  const [recoveryCode, setRecoveryCode] = useState('')
  const [recoveryNewPassword, setRecoveryNewPassword] = useState('')
  const [recoveryConfirmation, setRecoveryConfirmation] = useState('')
  const [newRecoveryCode, setNewRecoveryCode] = useState('')
  const [newRecoveryUser, setNewRecoveryUser] = useState<AccountUser | null>(null)
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
      if (registering) {
        const result = await api.register(username, password)
        setNewRecoveryCode(result.recovery_code)
        setNewRecoveryUser(result.user)
      } else {
        const result = await api.login(username, password)
        onAuthenticated(result.user)
      }
    } catch (reason) {
      setError(apiErrorMessage(reason))
    } finally {
      submitting.current = false
      setBusy(false)
    }
  }

  async function resetPassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (submitting.current) return
    setError('')
    if (!/^[A-Za-z0-9_]{3,32}$/.test(recoveryUsername)) {
      setError('用户名请使用 3–32 位英文字母、数字或下划线。'); return
    }
    if (recoveryNewPassword.length < 8 || recoveryNewPassword.length > 128) {
      setError('新密码长度应为 8–128 个字符。'); return
    }
    if (recoveryNewPassword !== recoveryConfirmation) {
      setError('两次输入的新密码不一致。'); return
    }
    submitting.current = true
    setBusy(true)
    try {
      const result = await api.resetPassword(recoveryUsername, recoveryCode, recoveryNewPassword)
      onAuthenticated(result.user)
    } catch (reason) {
      setError(apiErrorMessage(reason))
    } finally {
      submitting.current = false
      setBusy(false)
    }
  }

  if (newRecoveryCode) {
    return <main className="auth-shell">
      <div className="auth-layout"><section className="auth-card" aria-labelledby="recovery-title">
        <span className="section-kicker">SAVE THIS CODE</span>
        <h2 id="recovery-title">账户已创建</h2>
        <p className="auth-description">请立即保存恢复码。关闭此页面后将无法再次查看。</p>
        <div className="recovery-code" role="status">{newRecoveryCode}</div>
        <p className="auth-notice">恢复码只用于找回密码，请不要发给其他人，也不要提交到代码仓库。</p>
        <button type="button" className="primary-button full auth-submit" onClick={() => { if (newRecoveryUser) onAuthenticated(newRecoveryUser) }}>继续进入工作台 →</button>
      </section></div>
      <footer className="auth-footer">职得offer · 让每一段真实经历被看见</footer>
    </main>
  }

  if (forgotPassword) {
    return <main className="auth-shell">
      <div className="auth-layout">
        <section className="auth-intro">
          <div className="brand"><OwlLogo /><span>职得<span className="brand-offer">offer</span></span></div>
          <span className="eyebrow">ACCOUNT RECOVERY</span>
          <h1>找回你的<br />求职空间。</h1>
          <p>账户资料和求职材料都属于个人空间，恢复操作需要用户名与注册时生成的恢复码。</p>
          <div className="auth-promise"><UiIcon name="shield" /><span>不会仅凭用户名直接修改密码</span></div>
        </section>
        <section className="auth-card" aria-labelledby="auth-title">
          <span className="section-kicker">PASSWORD RECOVERY</span>
          <h2 id="auth-title">忘记密码</h2>
          <p className="auth-description">输入用户名、注册时获得的恢复码和新密码即可找回账户。</p>
          <form onSubmit={resetPassword}>
            <fieldset disabled={busy}>
              <label htmlFor="recovery-username">用户名</label>
              <input id="recovery-username" autoComplete="username" value={recoveryUsername} onChange={(e) => setRecoveryUsername(e.target.value)} required minLength={3} maxLength={32} pattern="[A-Za-z0-9_]{3,32}" spellCheck={false} />
              <label htmlFor="recovery-code">恢复码</label>
              <input id="recovery-code" autoComplete="off" value={recoveryCode} onChange={(e) => setRecoveryCode(e.target.value)} required minLength={8} maxLength={128} spellCheck={false} />
              <label htmlFor="recovery-password">新密码</label>
              <input id="recovery-password" type="password" autoComplete="new-password" value={recoveryNewPassword} onChange={(e) => setRecoveryNewPassword(e.target.value)} required minLength={8} maxLength={128} />
              <label htmlFor="recovery-confirmation">确认新密码</label>
              <input id="recovery-confirmation" type="password" autoComplete="new-password" value={recoveryConfirmation} onChange={(e) => setRecoveryConfirmation(e.target.value)} required minLength={8} maxLength={128} />
              {error && <p className="auth-error" role="alert">{error}</p>}
              <button type="submit" className="primary-button full auth-submit">{busy ? '正在处理…' : '重置密码并进入 →'}</button>
            </fieldset>
          </form>
          <p className="auth-notice" role="status">恢复码成功使用后会立即失效，其他设备上的旧登录也会被撤销。</p>
          <button type="button" className="secondary-button full auth-submit" onClick={() => { setForgotPassword(false); setError('') }}>返回登录</button>
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
