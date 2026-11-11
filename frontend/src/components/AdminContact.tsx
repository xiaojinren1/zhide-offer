import { useEffect, useId, useRef, useState } from 'react'
import { api } from '../lib/api'
import './admin-contact.css'

export const CONTACT_UPDATED_EVENT = 'zhide:contact-updated'

export default function AdminContact() {
  const [qq, setQq] = useState<string | null>(null)
  const [message, setMessage] = useState('')
  const dialog = useRef<HTMLDialogElement>(null)
  const title = useId()

  useEffect(() => {
    let active = true
    const refresh = () => api.contact().then(result => { if (active) setQq(result.qq) }).catch(() => {})
    void refresh()
    window.addEventListener(CONTACT_UPDATED_EVENT, refresh)
    return () => { active = false; window.removeEventListener(CONTACT_UPDATED_EVENT, refresh) }
  }, [])

  if (!qq) return null
  return <>
    <button className="secondary-button admin-contact-entry" type="button" aria-haspopup="dialog" onClick={() => {
      setMessage('')
      dialog.current?.showModal()
    }}>联系管理员</button>
    <dialog ref={dialog} className="admin-contact-dialog" aria-labelledby={title}>
      <h2 id={title}>联系管理员</h2>
      <p>作者 QQ <strong>{qq}</strong></p>
      <div className="admin-contact-actions">
        <button className="primary-button" type="button" onClick={async () => {
      try {
        await navigator.clipboard.writeText(qq)
        setMessage('QQ 号已复制。')
      } catch {
        setMessage('请选中上方号码手动复制。')
      }
        }}>复制 QQ 号</button>
        <button className="secondary-button" type="button" onClick={() => dialog.current?.close()}>关闭</button>
      </div>
      {message && <p role="status">{message}</p>}
    </dialog>
  </>
}
