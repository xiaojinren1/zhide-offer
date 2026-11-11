import { useEffect, useState } from 'react'
import { api } from '../../lib/api'
import type { ResumeAppearance } from './ResumePreview'
import { operationError } from './state'

export default function ResumeShare({ userId, markdown, appearance, canPublish }: {
  userId: string
  markdown: string
  appearance: ResumeAppearance
  canPublish: boolean
}) {
  const [share, setShare] = useState<Awaited<ReturnType<typeof api.currentResumeShare>>>()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  useEffect(() => {
    let active = true
    api.currentResumeShare().then(result => { if (active) setShare(result) })
      .catch(reason => { if (active) setError(operationError(reason)) })
    return () => { active = false }
  }, [])
  const href = share ? new URL(`/resume/share/${share.token}`, window.location.origin).href : ''

  async function change(revoke: boolean) {
    if (busy) return
    if (!window.confirm(revoke ? '撤回后，此链接将无法打开。确定撤回？'
      : '任何拿到链接的人都能查看本次发布的简历。请确认姓名、电话、邮箱及显示的证件照等信息可以公开。')) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      if (revoke) {
        await api.revokeResume(userId)
        setShare(null)
        setNotice('已撤回分享链接。')
      } else {
        setShare(await api.publishResume(userId, markdown, appearance))
        setNotice('在线简历已发布。')
      }
    } catch (reason) {
      setError(operationError(reason))
    } finally {
      setBusy(false)
    }
  }

  if (!canPublish && !share && !error) return null
  return <section className="panel resume-share-panel" aria-labelledby="resume-share-title">
    <div className="panel-heading">
      <h2 id="resume-share-title">在线分享</h2>
      <span className={share ? 'tag blue' : 'tag'}>{share ? '已发布' : share === null ? '未发布' : error ? '读取失败' : '读取中'}</span>
    </div>
    <p className="panel-description">{share
      ? '持链接的人无需登录即可查看。草稿改动在更新发布版本后同步。'
      : '发布后可以复制链接，发给招聘方查看。'}</p>
    {href && <div className="resume-share-link">
      <span>分享链接</span>
      <a href={href} target="_blank" rel="noopener noreferrer">{href}</a>
    </div>}
    <div className="resume-share-actions">
      {canPublish && <button type="button" className="primary-button" disabled={busy || share === undefined}
        onClick={() => void change(false)}>{share ? '更新发布版本' : '发布在线简历'}</button>}
      {share && <>
        <button type="button" className="secondary-button" onClick={async () => {
          try { await navigator.clipboard.writeText(href); setNotice('链接已复制。') }
          catch { setNotice('请手动复制上方链接。') }
        }}>复制链接</button>
        <button type="button" className="secondary-button" disabled={busy} onClick={() => void change(true)}>撤回链接</button>
      </>}
    </div>
    {error && <p className="warning-note" role="alert">{error}</p>}
    {notice && <p className="wb-success" role="status">{notice}</p>}
  </section>
}
