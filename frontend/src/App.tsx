import AdminContact from './components/AdminContact'
import posterOwl from './assets/poster-owl.png'
import { useCallback, useEffect, useRef, useState } from 'react'
import DiagnosePage from './pages/DiagnosePage'
import QualityPage from './pages/QualityPage'
import InterviewPage from './pages/InterviewPage'
import LibraryPage from './pages/LibraryPage'
import ResumeLibraryPage from './pages/ResumeLibraryPage'
import JobsPage from './pages/jobs/JobsPage'
import CommunityPage from './pages/community/CommunityPage'
import WorkbenchPage from './pages/WorkbenchPage'
import AuthPage from './pages/AuthPage'
import AccountPage from './pages/AccountPage'
import UserStats from './pages/UserStats'
import ModelPreferences from './pages/ModelPreferences'
import ModelUsage from './pages/ModelUsage'
import './pages/model-center.css'
import axios from 'axios'
import { OwlLogo, UiIcon } from './components/Brand'
import { api, apiErrorMessage, ACCOUNT_CHANGED_EVENT, invalidateAuthRequests, PROFILE_UPDATED_EVENT, SESSION_EXPIRED_EVENT, MODEL_CONFIGURATION_REQUIRED_EVENT } from './lib/api'
import { migrateLegacyModel } from './lib/modelStorage'
import type { AccountUser } from './lib/api'
import type { ResumeProfile } from './lib/types'
import { useWorkspace } from './lib/useWorkspace'
import type { WorkspacePage } from './lib/workspace'

type SettingsPage = 'account' | 'models' | 'admin' | 'resumes' | 'jobs' | 'community'
type Page = WorkspacePage | SettingsPage
const FLOW: Array<{ id: Page; name: string; icon: string }> = [
  { id: 'workbench', name: '材料整理与修改简历', icon: 'edit' },
  { id: 'interview', name: '模拟面试', icon: 'chat' },
]
export default function App() {
  const [user, setUser] = useState<AccountUser | null>(null)
  const [checking, setChecking] = useState(true)
  const [checkError, setCheckError] = useState('')
  const [modelRestoreError, setModelRestoreError] = useState('')
  const [notice, setNotice] = useState('')
  const identityCheck = useRef(0)
  const checkIdentity = useCallback(async (clearWorkspace = false) => {
    const generation = ++identityCheck.current
    invalidateAuthRequests()
    if (clearWorkspace) setUser(null)
    setChecking(true)
    setCheckError('')
    try {
      // Hydrate the full account profile so the persisted avatar is available
      // before the top bar renders after a refresh.
      const result = await api.profile()
      if (generation !== identityCheck.current) return
      try {
        if (!result.user.guest) await migrateLegacyModel(result.user.id, () => generation === identityCheck.current)
        if (generation === identityCheck.current) setModelRestoreError('')
      } catch (reason) {
        if (generation === identityCheck.current) setModelRestoreError(apiErrorMessage(reason))
      }
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
      setNotice('登录状态已失效，请重新登录。已保存的工作台会在登录后恢复，未保存的编辑可能丢失。')
    }
    const changed = () => {
      setNotice('账户状态已变化。登录后会加载对应账户已保存的工作台。')
      void checkIdentity(true)
    }
    const profileUpdated = () => {
      const generation = identityCheck.current
      void api.profile().then((result) => {
        if (generation === identityCheck.current) setUser(result.user)
      }).catch(() => undefined)
    }
    const focused = () => { if (document.visibilityState === 'visible') void checkIdentity() }
    window.addEventListener(SESSION_EXPIRED_EVENT, expire)
    window.addEventListener(ACCOUNT_CHANGED_EVENT, changed)
    window.addEventListener(PROFILE_UPDATED_EVENT, profileUpdated)
    window.addEventListener('focus', focused)
    document.addEventListener('visibilitychange', focused)
    return () => {
      ++identityCheck.current
      window.removeEventListener(SESSION_EXPIRED_EVENT, expire)
      window.removeEventListener(ACCOUNT_CHANGED_EVENT, changed)
      window.removeEventListener(PROFILE_UPDATED_EVENT, profileUpdated)
      window.removeEventListener('focus', focused)
      document.removeEventListener('visibilitychange', focused)
    }
  }, [checkIdentity])
  if (!user && (checking || checkError)) return <main className="auth-connection"><div className="brand"><OwlLogo /><span>职得<span className="brand-offer">offer</span></span></div><p role={checkError ? 'alert' : 'status'}>{checkError || '正在确认登录状态…'}</p>{checkError && <button className="primary-button" onClick={() => void checkIdentity()}>重新连接</button>}</main>
  if (!user) return <AuthPage notice={notice} onAuthenticated={() => { setNotice(''); void checkIdentity(true) }} />
  return <>
    {(checking || checkError) && <div className="notice" role={checkError ? 'alert' : 'status'}>{checkError || '正在核对账户…'}{checkError && <button className="secondary-button" onClick={() => void checkIdentity()}>重新连接</button>}</div>}
    {modelRestoreError && <div className="notice" role="alert">旧模型配置迁移失败，本地配置已保留。请刷新重试或在个人设置重新配置。{modelRestoreError}</div>}
    <div inert={checking || Boolean(checkError)}><AccountWorkspace key={user.id} user={user} onUserUpdated={setUser} onLoggedOut={() => {
      setNotice('你已退出登录。'); void checkIdentity(true)
    }} /></div>
  </>
}

function AccountWorkspace({ user, onUserUpdated, onLoggedOut }: { user: AccountUser; onUserUpdated: (user: AccountUser) => void; onLoggedOut: () => void }) {
  useEffect(() => {
    if (user.guest) return
    const heartbeat = () => {
      if (document.visibilityState === 'visible') void api.heartbeat().catch(() => {})
    }
    heartbeat()
    const timer = window.setInterval(heartbeat, 60_000)
    document.addEventListener('visibilitychange', heartbeat)
    return () => {
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', heartbeat)
    }
  }, [user.id, user.guest])
  const persistence = useWorkspace(user.id)
  const { state, update } = persistence
  const { profile, jd_text: jdText, jd_keywords: jdKeywords, markdown, source_text: sourceText, source_name: sourceName } = state
  const [canManage, setCanManage] = useState(false)
  // 站点还没有管理员时，给首个正式账号一个自助入口（公开部署忘了配名单也不至于死锁）
  const [canClaimAdmin, setCanClaimAdmin] = useState(false)
  const [claimingAdmin, setClaimingAdmin] = useState(false)
  useEffect(() => {
    if (user.guest) return
    let active = true
    api.userStats().then(result => { if (active) setCanManage(Boolean(result)) }).catch(() => {})
    api.adminBootstrap().then(result => { if (active) setCanClaimAdmin(Boolean(result?.claimable)) })
      .catch(() => { if (active) setCanClaimAdmin(false) })
    return () => { active = false }
  }, [user.guest, user.id])

  async function claimAdmin() {
    if (claimingAdmin || canManage) return
    if (!window.confirm('这个站点还没有管理员。领取后你将拥有管理权限（统计、反馈、角色、错误趋势）。仅当站点无任何管理员时才能领取，领取后成为首个管理员。继续？')) return
    setClaimingAdmin(true)
    try {
      await api.claimAdmin()
      setCanClaimAdmin(false)
      setCanManage(true)
    } catch (reason) {
      setCanClaimAdmin(false)
      window.alert(apiErrorMessage(reason))
    } finally {
      setClaimingAdmin(false)
    }
  }
  const [pageOverride, setPageOverride] = useState<SettingsPage | null>(null)
  const [modelModule, setModelModule] = useState<'config' | 'usage'>('config')
  const [workbenchEntryStep, setWorkbenchEntryStep] = useState<3 | 4>(3)
  const canOpen = (value: Page) => value === 'resumes' || value === 'jobs' || value === 'community' || value === 'account' || value === 'models' || (value === 'admin' && canManage) || value === 'memory' || value === 'workbench'
    || (value === 'diagnose' && Boolean(profile && jdText.trim() && markdown.trim()))
    || (value === 'quality' && Boolean(profile && markdown.trim()))
    || (value === 'interview' && Boolean(profile?.user_confirmed && jdText.trim() && markdown.trim()))
  const requestedPage: Page = pageOverride || state.page
  const page: Page = canOpen(requestedPage) ? requestedPage : 'workbench'
  useEffect(() => {
    if (page === 'workbench') setWorkbenchEntryStep(3)
  }, [page])
  const setPage = (value: Page, workbenchStep: 3 | 4 = 3) => {
    if (operationBusy.current || loggingOut || !canOpen(value)) return
    if (value === 'workbench') setWorkbenchEntryStep(workbenchStep)
    if (value === 'resumes' || value === 'jobs' || value === 'community' || value === 'account' || value === 'models' || value === 'admin') {
      setPageOverride(value)
    } else {
      setPageOverride(null)
      update((previous) => ({ ...previous, page: value }))
    }
  }
  const setMarkdown = (value: string) => update((previous) => ({ ...previous, markdown: value }))
  const setJdKeywords = (value: string[]) => update((previous) => ({ ...previous, jd_keywords: value }))
  const setSourceText = (value: string) => update((previous) => ({ ...previous, source_text: value }))
  const setSourceName = (value: string) => update((previous) => ({ ...previous, source_name: value }))
  const [busy, setBusyState] = useState(false)
  const operationBusy = useRef(false)
  const setBusy = useCallback((value: boolean) => { operationBusy.current = value; setBusyState(value) }, [])
  const [loggingOut, setLoggingOut] = useState(false)
  const [logoutError, setLogoutError] = useState('')
  const updateProfile = (value: ResumeProfile | null) => update((previous) => ({ ...previous, profile: value, markdown: '' }))
  const updateJd = (value: string) => update((previous) => ({ ...previous, jd_text: value, jd_keywords: [] }))
  const retentionLabel = { loading: '正在恢复工作台…', ready: '工作台已就绪 · 编辑后自动保存', pending: '有编辑尚未保存…', saving: '正在保存工作台…', saved: '工作台已保存', 'load-error': '工作台恢复失败', 'save-error': '工作台保存失败', conflict: '其他页面已更新，请处理版本冲突' }[persistence.phase]
  const restoreWorkspace = () => {
    if (operationBusy.current || loggingOut) return
    void persistence.load()
  }
  async function logout() {
    if (operationBusy.current || loggingOut) return
    if (user.guest && !window.confirm('结束试用会清除临时记录，确定退出？')) return
    setLoggingOut(true); setLogoutError('')
    try { if (!user.guest && (persistence.loaded || persistence.hasUnsaved())) await persistence.flush(); await api.logout(); onLoggedOut() }
    catch (reason) {
      if (axios.isAxiosError(reason) && reason.response?.status === 401) onLoggedOut()
      else setLogoutError(apiErrorMessage(reason))
    } finally { setLoggingOut(false) }
  }
  const modelDialog = useRef<HTMLDialogElement>(null)
  const [modelNotice, setModelNotice] = useState('')
  const [showingModelGuide, setShowingModelGuide] = useState(false)
  const guidedGuest = useRef(false)
  useEffect(() => {
    const show = (event: Event) => {
      setShowingModelGuide(false)
      setModelNotice((event as CustomEvent<string>).detail)
      if (modelDialog.current && !modelDialog.current.open) modelDialog.current.showModal()
    }
    window.addEventListener(MODEL_CONFIGURATION_REQUIRED_EVENT, show)
    return () => window.removeEventListener(MODEL_CONFIGURATION_REQUIRED_EVENT, show)
  }, [])

  useEffect(() => {
    if (!user.guest || !persistence.loaded || page === 'models' || guidedGuest.current) return
    const storageKey = 'jobagent:last-guided-guest'
    try {
      if (sessionStorage.getItem(storageKey) === user.id) return
    } catch { /* The mounted workspace still tracks whether the guide was shown. */ }
    let active = true
    void api.modelPreference().then(preference => {
      const dialog = modelDialog.current
      if (!active || preference?.has_api_key || !dialog || dialog.open) return
      guidedGuest.current = true
      try { sessionStorage.setItem(storageKey, user.id) } catch { /* Storage may be unavailable. */ }
      setShowingModelGuide(true)
      setModelNotice('配置自己的文本模型后，就能用真实材料体验简历生成和模拟面试。')
      dialog.showModal()
    }).catch(() => undefined)
    return () => { active = false }
  }, [page, persistence.loaded, user.guest, user.id])

  return <div className="app-shell">
    <dialog ref={modelDialog} className="model-config-dialog" aria-labelledby="model-config-title" aria-describedby="model-config-message">
      <h2 id="model-config-title">{showingModelGuide ? "开始试用：配置文本模型" : "需要先配置模型"}</h2>
      <p id="model-config-message">{modelNotice}</p>
      {showingModelGuide && <ol className="model-config-steps">
        <li>填写模型服务的 Base URL 和 API Key。</li>
        <li>从列表选择模型，或手动填写模型 ID。</li>
        <li>点击「测试并启用」，再返回工作台。</li>
      </ol>}
      <div className="model-config-actions">
        <button type="button" className="secondary-button" onClick={() => modelDialog.current?.close()}>稍后设置</button>
        <button type="button" className="primary-button" onClick={() => { modelDialog.current?.close(); setModelModule('config'); setPage('models') }}>前往模型配置</button>
      </div>
    </dialog>
    <header className="topbar"><a className="brand" href="#" onClick={(e) => { e.preventDefault(); if (!busy) setPage('workbench') }}><OwlLogo /><span>职得<span className="brand-offer">offer</span></span></a><div className="topbar-right"><AdminContact />{user.guest ? <button className="secondary-button" disabled={busy || loggingOut} onClick={() => setPage('models')}>临时配置模型</button> : <button className="account-entry" type="button" disabled={busy || loggingOut} onClick={() => setPage('account')} aria-label="打开个人中心"><span className="avatar small topbar-avatar">{user.avatar_url ? <img src={`/api/auth/avatar?v=${encodeURIComponent(user.avatar_url)}`} alt="" /> : user.username[0].toUpperCase()}</span><span className="account-name" title={user.username}>{user.username}</span><UiIcon name="chevron" /></button>}<button className="secondary-button account-logout" disabled={busy || loggingOut} onClick={logout}>{loggingOut ? '退出中…' : user.guest ? '结束试用' : '退出登录'}</button></div></header>
    <aside className="sidebar"><div className="sidebar-caption">我的求职流程</div><nav aria-label="求职流程">{FLOW.map((item, index) => { const allowed = canOpen(item.id); return <button key={item.id} disabled={busy || loggingOut || !persistence.loaded || !allowed} aria-disabled={!allowed} className={`nav-item ${page === item.id ? 'active' : ''}`} onClick={() => setPage(item.id)}><span className="flow-index">{index + 1}</span><UiIcon name={item.icon} /><span>{item.name}</span>{page === item.id && <span className="nav-dot" />}</button> })}</nav><div className="sidebar-secondary"><button className={`nav-item ${page === 'memory' ? 'active' : ''}`} disabled={busy || loggingOut || !persistence.loaded} onClick={() => setPage('memory')}><UiIcon name="folder" /><span>个人经历库</span></button><button type="button" className={`nav-item ${page === 'resumes' ? 'active' : ''}`} aria-current={page === 'resumes' ? 'page' : undefined} disabled={busy || loggingOut || !persistence.loaded} onClick={() => setPage('resumes')}><UiIcon name="folder" /><span>简历库</span></button><button type="button" className={`nav-item ${page === 'jobs' ? 'active' : ''}`} aria-current={page === 'jobs' ? 'page' : undefined} disabled={busy || loggingOut || !persistence.loaded} onClick={() => setPage('jobs')}><UiIcon name="folder" /><span>岗位收件箱</span></button>
      <button type="button" className={`nav-item ${page === 'community' ? 'active' : ''}`} aria-current={page === 'community' ? 'page' : undefined} disabled={busy || loggingOut || !persistence.loaded} onClick={() => setPage('community')}><UiIcon name="folder" /><span>面经与内推</span></button>
      <button type="button" className={`nav-item ${page === 'models' ? 'active' : ''}`} aria-current={page === 'models' ? 'page' : undefined} disabled={busy || loggingOut} onClick={() => setPage('models')}><UiIcon name="edit" /><span>模型中心</span></button>
      {canManage && <button type="button" className={`nav-item ${page === 'admin' ? 'active' : ''}`} aria-current={page === 'admin' ? 'page' : undefined} disabled={busy || loggingOut} onClick={() => setPage('admin')}><UiIcon name="shield" /><span>管理后台</span></button>}
      {!canManage && canClaimAdmin && <button type="button" className="nav-item nav-claim-admin" disabled={busy || loggingOut || claimingAdmin} onClick={() => void claimAdmin()}><UiIcon name="shield" /><span>{claimingAdmin ? '领取中…' : '成为首个管理员'}</span></button>}
    </div><div className="sidebar-bottom"><div className="sidebar-tip"><UiIcon name="shield" /><strong>工作台内完成闭环</strong><p>岗位匹配和简历检查会围绕当前简历逐项修改。</p></div></div></aside>
    <main className={pageOverride ? 'workspace workspace-settings' : 'workspace'}><div className="page-heading"><div><span className="eyebrow">{page === 'jobs' ? 'JOB INBOX' : page === 'community' ? 'COMMUNITY' : page === 'resumes' ? 'RESUME LIBRARY' : page === 'admin' ? 'ADMIN DASHBOARD' : page === 'models' ? 'MODEL CENTER' : page === 'account' ? 'ACCOUNT SETTINGS' : 'YOUR NEXT CHAPTER'}</span><h1>{page === 'jobs' ? '岗位收件箱' : page === 'community' ? '面经与内推' : page === 'resumes' ? '简历库' : page === 'admin' ? '管理后台' : page === 'models' ? '模型中心' : page === 'account' ? '个人中心' : '把真实经历，变成岗位竞争力'}</h1><p>{page === 'jobs' ? '把 JD 收进来，后面的匹配、定制和面试都用它。' : page === 'community' ? '看别人真实的面经与内推，也把自己的复盘匿名分享出来。' : page === 'resumes' ? '预览和下载当前工作台简历。' : page === 'admin' ? '查看站点趋势、处理反馈与管理角色。' : page === 'models' ? (user.guest ? '为本次试用配置文本和图片解析模型。' : '配置你的模型，查看调用和 Token 用量。') : page === 'account' ? '管理头像与登录密码。' : '整理经历，确认事实，为每个心仪岗位做好准备。'}</p></div>{!pageOverride && <div className="brand-companion" aria-hidden="true"><span className="brand-orbit" /><img src={posterOwl} alt="" width="180" height="180" /><span className="companion-caption">你的 AI 求职伙伴</span></div>}</div>
      {logoutError && <p className="auth-error account-error" role="alert">退出未成功：{logoutError}</p>}
      <div className="notice" role={persistence.error ? 'alert' : 'status'}><span>{user.guest ? "免注册试用 · 可在右上角临时配置自己的模型。退出或到期前，请先导出需要的简历。" : retentionLabel}{persistence.error && `：${persistence.error}`}</span>{persistence.savedAt && persistence.phase === 'saved' && <span className="muted"> · {new Date(persistence.savedAt).toLocaleTimeString('zh-CN')}</span>}{persistence.phase === 'load-error' && <button className="secondary-button" disabled={busy || loggingOut} onClick={restoreWorkspace}>重试恢复</button>}{persistence.phase === 'save-error' && <button className="secondary-button" disabled={loggingOut} onClick={() => void persistence.retrySave().catch(() => undefined)}>重试保存</button>}{persistence.phase === 'conflict' && <button className="secondary-button" disabled={busy || loggingOut} onClick={restoreWorkspace}>放弃本页编辑并加载服务器版本</button>}</div>
      <div inert={!persistence.loaded || loggingOut}>
      {persistence.loaded && page === 'workbench' && <WorkbenchPage initialStep={workbenchEntryStep} userId={user.id} guest={user.guest} savedAppearance={state.resume_appearance} onAppearanceChange={appearance => update(previous => ({ ...previous, resume_appearance: appearance }))} sourceText={sourceText} setSourceText={setSourceText} sourceName={sourceName} setSourceName={setSourceName} profile={profile} onProfileChange={updateProfile} jdText={jdText} onJdChange={updateJd} markdown={markdown} onMarkdownChange={setMarkdown} jdKeywords={jdKeywords} onJdKeywordsChange={setJdKeywords} busy={busy || loggingOut || !persistence.loaded} onBusyChange={setBusy} onDiagnose={() => setPage('diagnose')} onQuality={() => setPage('quality')} onInterview={() => setPage('interview')} />}
      {page === 'diagnose' && <div className="legacy-panel"><DiagnosePage jdText={jdText} setJdText={updateJd} profile={profile} markdown={markdown} onMarkdownChange={setMarkdown} busy={busy || loggingOut || !persistence.loaded} onBusyChange={setBusy} onDone={(_text, keywords) => setJdKeywords(keywords)} onEditResume={() => setPage('workbench')} onNext={() => setPage('quality')} /></div>}
      {page === 'quality' && <div className="legacy-panel"><QualityPage jdText={jdText} jdKeywords={jdKeywords} profile={profile} markdown={markdown} onMarkdownChange={setMarkdown} busy={busy || loggingOut || !persistence.loaded} onBusyChange={setBusy} onEditResume={() => setPage('workbench')} onNext={() => setPage('workbench', 4)} /></div>}
      {page === 'interview' && <div className="legacy-panel"><InterviewPage userId={user.id} jdText={jdText} profile={profile} markdown={markdown} /></div>}
      {persistence.loaded && page === 'resumes' && <ResumeLibraryPage markdown={markdown} appearance={state.resume_appearance}
        name={sourceName || profile?.name || '职得offer'} onOpenWorkbench={() => setPage('workbench', markdown.trim() ? 4 : 3)} />}
      {page === 'jobs' && <JobsPage key={user.id} userId={user.id} disabled={busy || loggingOut || !persistence.loaded} canManage={canManage}
        profile={profile} markdown={markdown}
        onUseJd={(text) => { updateJd(text); setPage('diagnose') }}
        onApplyPipeline={({ jdText, markdown: draft, keywords }) => {
          updateJd(jdText)
          setMarkdown(draft)
          setJdKeywords(keywords)
          setPage('quality')
        }} />}
      {page === 'community' && <CommunityPage key={user.id} userId={user.id} disabled={busy || loggingOut || !persistence.loaded} canManage={canManage} />}
      {page === 'memory' && <LibraryPage key={user.id} currentProfile={profile} hasUnsaved={persistence.hasUnsaved()} userId={user.id} resumeName={sourceName || profile?.name || '职得offer'} disabled={busy || loggingOut || !persistence.loaded} onLoad={(loadedProfile, meta) => {
        update((previous) => ({
          ...previous,
          profile: loadedProfile,
          source_text: loadedProfile.raw_text || '',
          source_name: meta.name || '已保存经历库',
          markdown: '',
          page: 'workbench',
        }))
      }} />}
      {page === 'admin' && canManage && <UserStats username={user.username} />}
      {page === 'account' && !user.guest && <AccountPage user={user} onUserChange={onUserUpdated} />}
      {page === 'models' && <div className="account-page">
        {!user.guest && <nav className="model-center-modules" aria-label="模型中心模块">
          <button type="button" aria-pressed={modelModule === 'config'} onClick={() => setModelModule('config')}>
            <strong>模型配置</strong>
            <span>管理文本和图片解析模型，测试连接并启用。</span>
          </button>
          <button type="button" aria-pressed={modelModule === 'usage'} onClick={() => setModelModule('usage')}>
            <strong>用量统计</strong>
            <span>按日期查看 Token 用量、模型排行和调用明细。</span>
          </button>
        </nav>}
        {user.guest || modelModule === 'config' ? <>
          <ModelPreferences userId={user.id} guest={user.guest} />
          <ModelPreferences userId={user.id} guest={user.guest} kind="vision" />
        </> : <ModelUsage />}
      </div>}
      </div>
      <footer className="workspace-footer"><span className="footer-brand">职得offer · 让每一段真实经历被看见</span><p><strong>免责声明：</strong>AI 生成内容仅供求职准备参考，请核对真实性后再使用；本产品不承诺面试或录用结果。</p><p><strong>原创声明：</strong>产品界面与功能由团队原创设计开发；用户上传材料及其知识产权归用户或原权利人所有。</p></footer>
    </main>
  </div>
}
