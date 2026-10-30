import { useEffect, useState } from 'react'
import DiagnosePage from './pages/DiagnosePage'
import QualityPage from './pages/QualityPage'
import InterviewPage from './pages/InterviewPage'
import WorkbenchPage from './pages/WorkbenchPage'
import { OwlLogo, UiIcon } from './components/Brand'
import { api } from './lib/api'
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
  const [page, setPage] = useState<Page>('workbench')
  const [profile, setProfile] = useState<ResumeProfile | null>(null)
  const [jdText, setJdText] = useState('')
  const [jdKeywords, setJdKeywords] = useState<string[]>([])
  const [markdown, setMarkdown] = useState('')
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState('连接服务中…')
  useEffect(() => { api.health().then((r) => setStatus(r.llm_configured ? '模型已配置 · 待实际验证' : '模型待配置 · 可先准备材料')).catch(() => setStatus('后端未连接 · 请检查启动状态')) }, [])
  const updateProfile = (value: ResumeProfile | null) => { setProfile(value); setMarkdown('') }
  const updateJd = (value: string) => { setJdText(value); setJdKeywords([]); setMarkdown(''); setProfile((previous) => previous ? { ...previous, user_confirmed: false } : null) }
  return <div className="app-shell">
    <header className="topbar"><a className="brand" href="#" onClick={(e) => { e.preventDefault(); if (!busy) setPage('workbench') }}><OwlLogo /><span>职得<span className="brand-offer">offer</span></span></a><div className="topbar-right"><span className="build-label">{status}</span><span className="avatar" aria-label="本机用户">我</span></div></header>
    <aside className="sidebar"><div className="sidebar-caption">我的求职空间</div><nav aria-label="主导航">{NAV.map((item) => <button key={item.id} disabled={busy} className={`nav-item ${page === item.id ? 'active' : ''}`} onClick={() => setPage(item.id)}><UiIcon name={item.icon} /><span>{item.name}</span>{page === item.id && <span className="nav-dot" />}</button>)}</nav><div className="sidebar-bottom"><div className="sidebar-tip"><UiIcon name="shield" /><strong>先确认，再生成</strong><p>每一份简历，都从你真实的经历出发。</p></div><div className="local-user"><span className="avatar small">我</span><div>本机工作空间<small>账户与隔离待接入</small></div></div></div></aside>
    <main className="workspace"><div className="page-heading"><div><span className="eyebrow">YOUR NEXT CHAPTER</span><h1>把真实经历，变成岗位竞争力</h1><p>整理经历，确认事实，为每个心仪岗位做好准备。</p></div><span className="heading-badge"><UiIcon name="spark" />懂你经历的求职 Agent</span></div>
      {page === 'workbench' && <WorkbenchPage profile={profile} onProfileChange={updateProfile} jdText={jdText} onJdChange={updateJd} markdown={markdown} onMarkdownChange={setMarkdown} jdKeywords={jdKeywords} busy={busy} onBusyChange={setBusy} onInterview={() => setPage('interview')} />}
      {page === 'diagnose' && <div className="legacy-panel"><DiagnosePage jdText={jdText} setJdText={updateJd} profile={profile} onDone={(_text, keywords) => setJdKeywords(keywords)} /></div>}
      {page === 'quality' && <div className="legacy-panel"><QualityPage jdText={jdText} jdKeywords={jdKeywords} profile={profile} markdown={markdown} /></div>}
      {page === 'interview' && <div className="legacy-panel"><div className="notice">当前提供面试题与回答要点。逐题作答、评分和语音将在后续接入。</div><InterviewPage jdText={jdText} profile={profile} markdown={markdown} /></div>}
      {page === 'memory' && <section className="memory-placeholder"><span className="empty-symbol"><UiIcon name="folder" /></span><h2>让经历成为下一次准备的起点</h2><p>本轮先完成材料确认与简历生成。个人账户、可管理的长期记忆和任务历史将在后续接入。</p><p className="muted">当前页面内容仅保留在本次浏览器会话中，刷新后会清空。你可以先下载 Markdown 简历。</p><button className="primary-button" onClick={() => setPage('workbench')}>返回简历工作台 →</button></section>}
      <footer className="workspace-footer"><span>职得offer · 让每一段真实经历被看见</span><span>开发预览 · 内容请在使用前核对</span></footer>
    </main>
  </div>
}
