import { useCallback, useEffect, useRef, useState } from 'react'
import DiagnosePage from './pages/DiagnosePage'
import QualityPage from './pages/QualityPage'
import InterviewPage from './pages/InterviewPage'
import WorkbenchPage from './pages/WorkbenchPage'
import AuthPage from './pages/AuthPage'
import axios from 'axios'
import { OwlLogo, UiIcon } from './components/Brand'
import { api, apiErrorMessage, ACCOUNT_CHANGED_EVENT, invalidateAuthRequests, SESSION_EXPIRED_EVENT } from './lib/api'
import type { AccountUser } from './lib/api'
import type { ResumeProfile } from './lib/types'

type Page = 'workbench' | 'diagnose' | 'quality' | 'interview' | 'memory'
const NAV: Array<{ id: Page; name: string; icon: string }> = [
  { id: 'workbench', name: '简历工作台', icon: 'edit' },
  { id: 'diagnose', name: '岗位匹配', icon: 'search' },
  { id: 'quality', name: '简历检查', icon: 'shield' },
  { id: 'interview', name: '面试话术', icon: 'chat' },
  { id: 'memory', name: '个人记忆', icon: 'folder' },
]
export default function App() {
  const [user, setUser] = useState<AccountUser | null>(null)
  const [checking, setChecking] = useState(true)
  const [checkError, setCheckError] = useState('')
  const [notice, setNotice] = useState('')
  const identityCheck = useRef(0)
  const checkIdentity = useCallback(async (clearWorkspace = false) => {
    const generation = ++identityCheck.current
    invalidateAuthRequests()
    if (clearWorkspace) setUser(null)
    setChecking(true)
    setCheckError('')
    try {
      const result = await api.me()
      if (generation === identityCheck.current) setUser(result.user)
    } catch (reason) {
      if (generation !== identityCheck.current) return
      if (axios.isAxiosError(reason) && reason.response?.status === 401) setUser(null)
      else setCheckError(apiErrorMessage(reason))
    } finally {
      if (generation === identityCheck.current) setChecking(false)
    }
  }, [])
  useEffect(() => {
    void checkIdentity()
    const expire = () => {
      ++identityCheck.current
      invalidateAuthRequests()
      setUser(null); setChecking(false); setCheckError('')
      setNotice('登录状态已失效，请重新登录。工作台中的临时内容已清空。')
    }
    const changed = () => {
      setNotice('账户状态已变化，工作台中的临时内容已清空。')
      void checkIdentity(true)
    }
    const focused = () => { if (document.visibilityState === 'visible') void checkIdentity() }
    window.addEventListener(SESSION_EXPIRED_EVENT, expire)
    window.addEventListener(ACCOUNT_CHANGED_EVENT, changed)
    window.addEventListener('focus', focused)
    document.addEventListener('visibilitychange', focused)
    return () => {
      ++identityCheck.current
      window.removeEventListener(SESSION_EXPIRED_EVENT, expire)
      window.removeEventListener(ACCOUNT_CHANGED_EVENT, changed)
      window.removeEventListener('focus', focused)
      document.removeEventListener('visibilitychange', focused)
    }
  }, [checkIdentity])
  if (!user && (checking || checkError)) return <main className="auth-connection"><div className="brand"><OwlLogo /><span>职得<span className="brand-offer">offer</span></span></div><p role={checkError ? 'alert' : 'status'}>{checkError || '正在确认登录状态…'}</p>{checkError && <button className="primary-button" onClick={() => void checkIdentity()}>重新连接</button>}</main>
  if (!user) return <AuthPage notice={notice} onAuthenticated={() => { setNotice(''); void checkIdentity(true) }} />
  return <>
    {(checking || checkError) && <div className="notice" role={checkError ? 'alert' : 'status'}>{checkError || '正在核对账户…'}{checkError && <button className="secondary-button" onClick={() => void checkIdentity()}>重新连接</button>}</div>}
    <div inert={checking || Boolean(checkError)}><AccountWorkspace key={user.id} user={user} onLoggedOut={() => {
      setNotice('你已退出登录。'); void checkIdentity(true)
    }} /></div>
  </>
}

function AccountWorkspace({ user, onLoggedOut }: { user: AccountUser; onLoggedOut: () => void }) {
  const [page, setPage] = useState<Page>('workbench')
  const [profile, setProfile] = useState<ResumeProfile | null>(null)
  const [jdText, setJdText] = useState('')
  const [jdKeywords, setJdKeywords] = useState<string[]>([])
  const [markdown, setMarkdown] = useState('')
  const [busy, setBusy] = useState(false)
  const [loggingOut, setLoggingOut] = useState(false)
  const [logoutError, setLogoutError] = useState('')
  const [status, setStatus] = useState('连接服务中…')
  useEffect(() => { api.health().then((r) => setStatus(r.llm_configured ? '模型已配置 · 待实际验证' : '模型待配置 · 可先准备材料')).catch(() => setStatus('后端未连接 · 请检查启动状态')) }, [])
  const updateProfile = (value: ResumeProfile | null) => { setProfile(value); setMarkdown('') }
  const updateJd = (value: string) => { setJdText(value); setJdKeywords([]); setMarkdown(''); setProfile((previous) => previous ? { ...previous, user_confirmed: false } : null) }
  async function logout() {
    if (busy || loggingOut) return
    setLoggingOut(true); setLogoutError('')
    try { await api.logout(); onLoggedOut() }
    catch (reason) {
      if (axios.isAxiosError(reason) && reason.response?.status === 401) onLoggedOut()
      else setLogoutError(apiErrorMessage(reason))
    } finally { setLoggingOut(false) }
  }
  return <div className="app-shell">
    <header className="topbar"><a className="brand" href="#" onClick={(e) => { e.preventDefault(); if (!busy) setPage('workbench') }}><OwlLogo /><span>职得<span className="brand-offer">offer</span></span></a><div className="topbar-right"><span className="build-label">{status}</span><span className="account-name" title={user.username}>{user.username}</span><button className="secondary-button account-logout" disabled={busy || loggingOut} onClick={logout}>{loggingOut ? '退出中…' : '退出登录'}</button></div></header>
    <aside className="sidebar"><div className="sidebar-caption">我的求职空间</div><nav aria-label="主导航">{NAV.map((item) => <button key={item.id} disabled={busy || loggingOut} className={`nav-item ${page === item.id ? 'active' : ''}`} onClick={() => setPage(item.id)}><UiIcon name={item.icon} /><span>{item.name}</span>{page === item.id && <span className="nav-dot" />}</button>)}</nav><div className="sidebar-bottom"><div className="sidebar-tip"><UiIcon name="shield" /><strong>先确认，再生成</strong><p>每一份简历，都从你真实的经历出发。</p></div><div className="local-user"><span className="avatar small">{user.username[0].toUpperCase()}</span><div className="account-sidebar-name"><span title={user.username}>{user.username}</span><small>独立账户 · 工作台尚未自动保存</small></div></div></div></aside>
    <main className="workspace"><div className="page-heading"><div><span className="eyebrow">YOUR NEXT CHAPTER</span><h1>把真实经历，变成岗位竞争力</h1><p>整理经历，确认事实，为每个心仪岗位做好准备。</p></div><span className="heading-badge"><UiIcon name="spark" />懂你经历的求职 Agent</span></div>
      {logoutError && <p className="auth-error account-error" role="alert">退出未成功：{logoutError}</p>}
      {page === 'workbench' && <WorkbenchPage profile={profile} onProfileChange={updateProfile} jdText={jdText} onJdChange={updateJd} markdown={markdown} onMarkdownChange={setMarkdown} jdKeywords={jdKeywords} busy={busy || loggingOut} onBusyChange={setBusy} onInterview={() => setPage('interview')} />}
      {page === 'diagnose' && <div className="legacy-panel"><DiagnosePage jdText={jdText} setJdText={updateJd} profile={profile} onDone={(_text, keywords) => setJdKeywords(keywords)} /></div>}
      {page === 'quality' && <div className="legacy-panel"><QualityPage jdText={jdText} jdKeywords={jdKeywords} profile={profile} markdown={markdown} /></div>}
      {page === 'interview' && <div className="legacy-panel"><div className="notice">当前提供面试题与回答要点。逐题作答、评分和语音将在后续接入。</div><InterviewPage jdText={jdText} profile={profile} markdown={markdown} /></div>}
      {page === 'memory' && <section className="memory-placeholder"><span className="empty-symbol"><UiIcon name="folder" /></span><h2>让经历成为下一次准备的起点</h2><p>你的账户已就绪。可管理的长期记忆、工作台保存和任务历史将在后续接入。</p><p className="muted">刷新后会保留登录状态，但当前工作台内容会清空。退出前请下载需要保留的 Markdown 简历。</p><button className="primary-button" onClick={() => setPage('workbench')}>返回简历工作台 →</button></section>}
      <footer className="workspace-footer"><span>职得offer · 让每一段真实经历被看见</span><span>开发预览 · 内容请在使用前核对</span></footer>
    </main>
  </div>
}
