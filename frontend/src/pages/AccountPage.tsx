import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { api, apiErrorMessage, PROFILE_UPDATED_EVENT } from '../lib/api'
import type { AccountUser } from '../lib/api'

const MAX_AVATAR_SIZE = 2 * 1024 * 1024
const AVATAR_TYPES = new Set(['image/jpeg', 'image/png', 'image/webp'])

export default function AccountPage({ user, onUserChange }: {
  user: AccountUser
  onUserChange: (user: AccountUser) => void
}) {
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [passwordBusy, setPasswordBusy] = useState(false)
  const [avatarBusy, setAvatarBusy] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const fileInput = useRef<HTMLInputElement>(null)
  const avatarSrc = user.avatar_url ? `/api/auth/avatar?v=${encodeURIComponent(user.avatar_url)}` : ''

  useEffect(() => {
    let active = true
    const refresh = async () => {
      try {
        const result = await api.profile()
        if (active) onUserChange(result.user)
      } catch (reason) {
        if (active) setError(apiErrorMessage(reason))
      }
    }
    void refresh()
    window.addEventListener(PROFILE_UPDATED_EVENT, refresh)
    return () => {
      active = false
      window.removeEventListener(PROFILE_UPDATED_EVENT, refresh)
    }
  }, [onUserChange])

  async function submitPassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    setSuccess('')
    if (newPassword.length < 8 || newPassword.length > 128) {
      setError('新密码长度应为 8–128 个字符。')
      return
    }
    if (newPassword !== confirmation) {
      setError('两次输入的新密码不一致。')
      return
    }
    setPasswordBusy(true)
    try {
      const result = await api.changePassword(currentPassword, newPassword)
      onUserChange({ ...user, ...result.user })
      setCurrentPassword('')
      setNewPassword('')
      setConfirmation('')
      setSuccess('密码已更新。')
    } catch (reason) {
      setError(apiErrorMessage(reason))
    } finally {
      setPasswordBusy(false)
    }
  }

  async function uploadAvatar(file?: File) {
    if (!file) return
    setError('')
    setSuccess('')
    if (!AVATAR_TYPES.has(file.type)) {
      setError('请选择 JPEG、PNG 或 WebP 图片。')
      return
    }
    if (file.size > MAX_AVATAR_SIZE) {
      setError('头像不能超过 2 MiB。')
      return
    }
    setAvatarBusy(true)
    try {
      await api.uploadAvatar(file)
      const result = await api.profile()
      onUserChange(result.user)
      setSuccess('头像已更新。')
    } catch (reason) {
      setError(apiErrorMessage(reason))
    } finally {
      setAvatarBusy(false)
      if (fileInput.current) fileInput.current.value = ''
    }
  }

  async function removeAvatar() {
    setError('')
    setSuccess('')
    setAvatarBusy(true)
    try {
      await api.removeAvatar()
      const result = await api.profile()
      onUserChange(result.user)
      setSuccess('头像已移除。')
    } catch (reason) {
      setError(apiErrorMessage(reason))
    } finally {
      setAvatarBusy(false)
    }
  }

  return <section className="account-page" aria-labelledby="avatar-title">
    {(error || success) && <p className={error ? 'auth-error' : 'account-success'} role={error ? 'alert' : 'status'}>{error || success}</p>}
    <section className="account-section" aria-labelledby="avatar-title">
      <div className="account-section-title"><h3 id="avatar-title">个人头像</h3><p>支持 JPEG、PNG 或 WebP，最大 2 MiB。</p></div>
      <div className="account-avatar-row">
        <div className="account-avatar" aria-label={user.avatar_url ? `${user.username}的头像` : '默认头像'}>
          {avatarSrc ? <img src={avatarSrc} alt="" onError={(event) => { event.currentTarget.hidden = true }} /> : <span>{user.username.slice(0, 1).toUpperCase()}</span>}
        </div>
        <div className="account-avatar-actions">
          <input ref={fileInput} className="visually-hidden" type="file" accept="image/jpeg,image/png,image/webp" aria-label="选择头像图片" disabled={avatarBusy} onChange={(event) => void uploadAvatar(event.currentTarget.files?.[0])} />
          <button type="button" className="primary-button" disabled={avatarBusy} onClick={() => fileInput.current?.click()}>{avatarBusy ? '处理中…' : '上传头像'}</button>
          {user.avatar_url && <button type="button" className="secondary-button" disabled={avatarBusy} onClick={() => void removeAvatar()}>移除头像</button>}
          <span className="field-hint">账户名：{user.username}</span>
        </div>
      </div>
    </section>
    <section className="account-section" aria-labelledby="password-title">
      <div className="account-section-title"><h3 id="password-title">修改密码</h3><p>修改后当前登录状态将继续有效。</p></div>
      <form className="account-password-form" onSubmit={submitPassword}>
        <label htmlFor="current-password">当前密码</label>
        <input id="current-password" type="password" autoComplete="current-password" required maxLength={128} value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} />
        <label htmlFor="new-password">新密码</label>
        <input id="new-password" type="password" autoComplete="new-password" required minLength={8} maxLength={128} value={newPassword} onChange={(event) => setNewPassword(event.target.value)} />
        <p className="field-hint">新密码长度为 8–128 个字符。</p>
        <label htmlFor="confirm-new-password">确认新密码</label>
        <input id="confirm-new-password" type="password" autoComplete="new-password" required minLength={8} maxLength={128} value={confirmation} onChange={(event) => setConfirmation(event.target.value)} />
        <button type="submit" className="primary-button account-password-submit" disabled={passwordBusy}>{passwordBusy ? '正在保存…' : '更新密码'}</button>
      </form>
    </section>
  </section>
}
