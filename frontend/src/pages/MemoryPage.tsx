import { useEffect, useRef, useState } from 'react'
import { api, apiErrorMessage, ACCOUNT_CHANGED_EVENT, SESSION_EXPIRED_EVENT } from '../lib/api'
import { downloadMarkdown, downloadPdf, downloadWord } from '../lib/export'
import type { ResumeProfile } from '../lib/types'
import { emptyWorkspace, isWorkspaceState } from '../lib/workspace'
import './memory/memory.css'

type SavedProfile = { id: string; name: string; saved_at: string; experience_count: number }
type ProfileMeta = { id: string; name: string; saved_at: string }
type Detail = { profile: ResumeProfile; meta: ProfileMeta }
type Props = {
  userId: string
  onLoad: (profile: ResumeProfile, meta: ProfileMeta) => void
  markdown?: string
  resumeName?: string
  disabled?: boolean
}

/** 载入旧快照后必须重新核对，不能继承历史确认状态或原来的生成稿。 */
export function profileForWorkbench(profile: ResumeProfile): ResumeProfile {
  return { ...structuredClone(profile), user_confirmed: false }
}

export default function MemoryPage({ userId, onLoad, markdown = '', resumeName = '职得offer', disabled = false }: Props) {
  const [profiles, setProfiles] = useState<SavedProfile[]>([])
  const [detail, setDetail] = useState<Detail | null>(null)
  const [pending, setPending] = useState<SavedProfile | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [available, setAvailable] = useState(true)
  const epoch = useRef(0)
  const lock = useRef(false)
  const exportController = useRef<AbortController | null>(null)
  const blocked = disabled || busy || loading || !available

  async function refresh(ticket = epoch.current) {
    if (lock.current) return
    lock.current = true
    setLoading(true); setError(''); setMessage(''); setDetail(null); setPending(null)
    try {
      const result = await api.listProfiles()
      if (ticket !== epoch.current) return
      if (!result.ok || !result.profiles) throw new Error(result.error || '读取经历库失败，请重试。')
      setProfiles(result.profiles)
    } catch (err) {
      if (ticket === epoch.current) setError(apiErrorMessage(err))
    } finally {
      if (ticket === epoch.current) { lock.current = false; setLoading(false) }
    }
  }

  useEffect(() => {
    const ticket = ++epoch.current
    lock.current = false
    setProfiles([]); setDetail(null); setPending(null); setAvailable(true); setBusy(false)
    void refresh(ticket)
    const invalidate = () => {
      ++epoch.current
      lock.current = false
      exportController.current?.abort()
      setProfiles([]); setDetail(null); setPending(null); setError('账户状态已变化，请重新登录后查看。')
      setAvailable(false); setBusy(false); setLoading(false); setMessage('')
    }
    window.addEventListener(ACCOUNT_CHANGED_EVENT, invalidate)
    window.addEventListener(SESSION_EXPIRED_EVENT, invalidate)
    return () => {
      ++epoch.current
      exportController.current?.abort()
      window.removeEventListener(ACCOUNT_CHANGED_EVENT, invalidate)
      window.removeEventListener(SESSION_EXPIRED_EVENT, invalidate)
    }
  }, [userId])

  async function view(item: SavedProfile) {
    if (blocked || lock.current) return
    lock.current = true
    const ticket = epoch.current
    setBusy(true); setError(''); setMessage(''); setDetail(null); setPending(null)
    try {
      const result = await api.loadProfile(item.id)
      if (ticket !== epoch.current) return
      if (!result.ok || !result.profile || !result.meta) throw new Error(result.error || '经历库无法读取，请刷新列表后重试。')
      if (!isWorkspaceState({ ...emptyWorkspace(), profile: result.profile })) throw new Error('经历库结构不完整，无法载入。')
      setDetail({ profile: result.profile, meta: result.meta })
    } catch (err) { if (ticket === epoch.current) setError(apiErrorMessage(err)) }
    finally { if (ticket === epoch.current) { lock.current = false; setBusy(false) } }
  }

  async function remove() {
    if (blocked || lock.current || !pending) return
    lock.current = true
    const ticket = epoch.current
    const item = pending
    setBusy(true); setError(''); setMessage('')
    try {
      const result = await api.deleteProfile(item.id)
      if (ticket !== epoch.current) return
      if (!result.ok) throw new Error(result.error || '删除没有完成，请重试。')
      setProfiles(previous => previous.filter(profile => profile.id !== item.id))
      if (detail?.meta.id === item.id) setDetail(null)
      setPending(null); setMessage('经历库已删除。已载入的工作台和面试记录不受影响。')
    } catch (err) { if (ticket === epoch.current) setError(apiErrorMessage(err)) }
    finally { if (ticket === epoch.current) { lock.current = false; setBusy(false) } }
  }

  function load() {
    if (blocked || !detail || lock.current) return
    setError('')
    try { onLoad(profileForWorkbench(detail.profile), detail.meta) }
    catch (err) { setError(apiErrorMessage(err)) }
  }

  async function exportResume(format: 'md' | 'docx' | 'pdf') {
    if (blocked || lock.current) return
    lock.current = true
    const ticket = epoch.current
    setBusy(true); setError(''); setMessage('')
    exportController.current = new AbortController()
    try {
      if (format === 'md') downloadMarkdown(markdown, resumeName)
      else if (format === 'docx') await downloadWord(markdown, resumeName, exportController.current.signal)
      else await downloadPdf(markdown, resumeName, exportController.current.signal)
      if (ticket === epoch.current) setMessage('已发起下载，请在浏览器下载列表中查看。')
    } catch (err) { if (ticket === epoch.current) setError(apiErrorMessage(err)) }
    finally { if (ticket === epoch.current) { lock.current = false; setBusy(false) } }
  }

  return <div className="role-d-memory" aria-busy={loading || busy}>
    <section className="panel memory-intro"><div><span className="section-kicker">PERSONAL MEMORY</span><h2>让真实经历，成为下一次准备的起点</h2><p>仅展示当前账户保存的经历库。载入后请重新确认事实，再生成面向新岗位的简历。</p></div><button className="secondary-button" disabled={disabled || busy || loading || !available} onClick={() => void refresh()}>刷新列表</button></section>
    {error && <p className="error-banner" role="alert">{error}</p>}
    {message && <p className="notice" role="status">{message}</p>}
    <div className="memory-layout">
      <section className="panel memory-list" aria-label="已保存经历库"><h3>我的经历库 <span className="muted">{profiles.length}</span></h3>
        {loading ? <p role="status">正在读取经历库…</p> : !profiles.length && !error ? <p className="memory-empty">还没有保存的经历库。先在工作台整理、确认事实并保存，随后即可在此查看。</p> : null}
        <ul>{profiles.map(item => <li key={item.id}>
          <h4>{item.name || '未命名经历库'}</h4><p className="muted">保存于 {item.saved_at} · {item.experience_count} 段经历</p>
          <div className="memory-actions"><button className="secondary-button" disabled={blocked} onClick={() => void view(item)}>查看 {item.name || '经历库'}</button><button className="memory-danger" disabled={blocked} onClick={() => { setPending(item); setError(''); setMessage('') }}>删除 {item.name || '经历库'}</button></div>
        </li>)}</ul>
      </section>
      <section className="panel memory-detail" aria-label="经历库详情"><h3>经历库详情</h3>
        {!detail ? <p className="memory-empty">选择左侧经历库查看内容。原始上传文件不在此保留。</p> : <>
          <h4>{detail.meta.name || '未命名经历库'}</h4><p className="muted">保存于 {detail.meta.saved_at}</p><p>{detail.profile.name}</p>
          {detail.profile.education?.length > 0 && <div><h4>教育背景</h4><ul>{detail.profile.education.map((entry, index) => <li key={index}>{entry}</li>)}</ul></div>}
          {detail.profile.experiences.map((experience, index) => <article key={index}><h4>{experience.name || '未命名经历'}</h4><p className="muted">{[experience.role, experience.period].filter(Boolean).join(' · ')}</p><ul>{(experience.actions || []).map((entry, i) => <li key={`a${i}`}>{entry}</li>)}{(experience.results || []).map((entry, i) => <li key={`r${i}`}>{entry}</li>)}</ul>{experience.skills?.length > 0 && <p>相关技能：{experience.skills.join('、')}</p>}</article>)}
          {detail.profile.skills?.length > 0 && <p>技能：{detail.profile.skills.join('、')}</p>}
          <p className="notice">载入将替换工作台材料并清空旧简历；岗位 JD 保留。事实确认会撤销，需要重新核对。</p>
          <button className="primary-button" disabled={blocked} onClick={load}>确认替换材料并载入工作台</button>
        </>}
      </section>
    </div>
    {pending && <section className="panel memory-delete" aria-label="删除确认"><h3>确认删除“{pending.name || '未命名经历库'}”？</h3><p>此操作不可撤销。已载入的工作台及面试记录不会删除。</p><div className="memory-actions"><button className="memory-danger" disabled={blocked} onClick={() => void remove()}>确认永久删除</button><button className="secondary-button" disabled={blocked} onClick={() => setPending(null)}>取消删除</button></div></section>}
    <section className="panel memory-export"><h3>导出当前简历</h3><p>导出工作台当前生成或编辑的正文，而非经历库原始材料。请逐句核对后用于投递。</p><div className="memory-actions"><button className="secondary-button" disabled={blocked || !markdown.trim()} onClick={() => void exportResume('md')}>下载 Markdown</button><button className="secondary-button" disabled={blocked || !markdown.trim()} onClick={() => void exportResume('docx')}>下载 Word</button><button className="primary-button" disabled={blocked || !markdown.trim()} onClick={() => void exportResume('pdf')}>下载 PDF</button></div>{!markdown.trim() && <p className="muted">暂无简历正文，请先在工作台生成。</p>}<p className="muted">支持 Markdown、Word 和 PDF 导出；复杂表格和图片保留文本，不抓取外链。</p></section>
  </div>
}
