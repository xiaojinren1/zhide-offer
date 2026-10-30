import { useState } from 'react'
import axios from 'axios'
import { api } from '../lib/api'
import type { Experience, ResumeProfile } from '../lib/types'
import { UiIcon } from '../components/Brand'
interface Props {
  profile: ResumeProfile | null; onProfileChange: (profile: ResumeProfile | null) => void
  jdText: string; onJdChange: (text: string) => void
  markdown: string; onMarkdownChange: (text: string) => void
  jdKeywords: string[]; busy: boolean; onBusyChange: (busy: boolean) => void; onInterview: () => void
}
const SAMPLE = '陈同学\n某大学，本科，2022.09—2026.06\n求职方向：产品经理\n项目：校园活动报名流程优化，2025.03—2025.06\n角色：项目成员\n负责收集同学的报名反馈，整理重复填报、信息分散等问题，绘制报名流程原型，并与开发同学沟通需求。\n产出：需求文档与流程原型，协助完成反馈整理。\n技能：需求分析、原型设计、用户反馈整理、跨团队协作。'
const SAMPLE_JD = '产品经理（示例岗位）\n工作职责：收集用户需求，分析业务流程，完成产品原型与需求文档，与研发团队沟通并推动方案落地。\n岗位要求：具备需求分析、原型设计和沟通协作能力，有校园项目或实习经历。'
const emptyExperience = (): Experience => ({ kind: 'project', name: '', role: '', period: '', actions: [], results: [], skills: [] })
function errorText(error: unknown) {
  if (axios.isAxiosError(error)) return String(error.response?.data?.error || error.response?.data?.detail || error.message)
  return error instanceof Error ? error.message : String(error)
}
export default function WorkbenchPage({ profile, onProfileChange, jdText, onJdChange, markdown, onMarkdownChange, jdKeywords, busy, onBusyChange, onInterview }: Props) {
  const [sourceText, setSourceText] = useState('')
  const [sourceName, setSourceName] = useState('')
  const [activity, setActivity] = useState('')
  const [error, setError] = useState('')
  const [numberWarnings, setNumberWarnings] = useState<string[]>([])
  const [previewMode, setPreviewMode] = useState<'preview' | 'edit'>('preview')
  const stage = markdown ? 3 : profile ? 2 : 1
  const resetOutput = () => { setNumberWarnings([]); setError('') }
  const editProfile = (value: ResumeProfile) => { onProfileChange({ ...value, user_confirmed: false }); resetOutput() }
  const editExperience = (index: number, patch: Partial<Experience>) => {
    if (profile) editProfile({ ...profile, experiences: profile.experiences.map((item, i) => i === index ? { ...item, ...patch } : item) })
  }
  const parse = async (file?: File) => {
    if (busy || (!file && !sourceText.trim())) return
    resetOutput(); onBusyChange(true); setActivity('正在整理材料…'); onProfileChange(null)
    try {
      const result = file ? await api.parseResumeFile(file) : await api.parseResumeText(sourceText)
      if (!result.ok || !result.profile) throw new Error(result.error || '材料解析失败，请重试')
      onProfileChange({ ...result.profile, user_confirmed: false })
      setSourceText(result.raw_text || result.profile.raw_text || sourceText)
      setSourceName(file?.name || '文本材料')
    } catch (err) { setError(errorText(err)) }
    finally { onBusyChange(false); setActivity('') }
  }
  const generate = async () => {
    if (busy || !profile?.user_confirmed || !jdText.trim()) return
    resetOutput(); onMarkdownChange(''); onBusyChange(true); setActivity('正在生成并检查简历…')
    try {
      const result = await api.generateResume(jdText, profile, jdKeywords)
      if (!result.ok || !result.markdown?.trim()) throw new Error(result.error || '未收到简历内容，请重试')
      onMarkdownChange(result.markdown); setNumberWarnings(result.untraceable || [])
    } catch (err) { setError(errorText(err)) }
    finally { onBusyChange(false); setActivity('') }
  }
  const download = () => {
    const url = URL.createObjectURL(new Blob([markdown], { type: 'text/markdown;charset=utf-8' }))
    const a = document.createElement('a'); a.href = url; a.download = `${profile?.name || '职得offer'}-定向简历.md`; a.click(); URL.revokeObjectURL(url)
  }
  return <>
    <ol className="stepper" aria-label="求职准备进度">{['整理材料', '确认事实', '生成简历', '准备面试'].map((name, i) => <li key={name} className={stage === i + 1 ? 'current' : stage > i + 1 ? 'complete' : ''}><span className="step-number">{stage > i + 1 ? <UiIcon name="check" /> : i + 1}</span><span>{name}</span>{i < 3 && <span className="step-line" />}</li>)}</ol>
    {error && <div className="error-banner" role="alert"><strong>这一步没有完成</strong><span>{error}</span><button onClick={() => setError('')} aria-label="关闭错误提示">×</button></div>}
    {busy && <div className="activity-banner" role="status"><span className="spinner" />{activity}<span className="muted">请稍候，完成后可继续编辑。</span></div>}
    <div className="workbench-grid">
      <section className="panel materials-panel"><div className="panel-heading"><div><span className="section-kicker">01 / MATERIALS</span><h2>求职材料</h2></div><UiIcon name="folder" /></div><fieldset disabled={busy}>
        <label className="upload-zone"><input type="file" accept=".txt,.md,.docx,.pdf" onChange={(e) => { const file = e.target.files?.[0]; if (file) void parse(file); e.target.value = '' }} /><span className="upload-icon"><UiIcon name="upload" /></span><strong>上传简历或经历材料</strong><span>Word · 文字 PDF · TXT · Markdown</span></label>
        {sourceName && <div className="source-chip"><UiIcon name="file" /><span>{sourceName}</span><span className="tag blue">已整理</span></div>}
        <div className="field-heading"><label htmlFor="source-text">或粘贴你的经历</label><button className="text-button" onClick={() => { setSourceText(SAMPLE); setSourceName(''); onProfileChange(null); onJdChange(SAMPLE_JD); resetOutput() }}>填入演示材料</button></div>
        <textarea id="source-text" className="source-text" value={sourceText} placeholder="项目、实习、工作或校园经历都可以。先写清你做过什么，无需提前润色。" onChange={(e) => { setSourceText(e.target.value); setSourceName(''); onProfileChange(null); resetOutput() }} />
        <button className="secondary-button full" disabled={!sourceText.trim()} onClick={() => void parse()}><UiIcon name="spark" />整理文本材料</button><div className="section-divider" />
        <label className="field-label" htmlFor="jd-text">目标岗位 JD <span>不限岗位</span></label><textarea id="jd-text" className="jd-text" value={jdText} onChange={(e) => { onJdChange(e.target.value); resetOutput() }} placeholder="粘贴岗位职责和任职要求，让匹配有据可依。" /><p className="field-hint">输入目标岗位后，AI 会调整经历重点与表述。</p>
      </fieldset></section>
      <section className="panel facts-panel"><div className="panel-heading"><div><span className="section-kicker">02 / YOUR STORY</span><h2>关键事实，先由你确认</h2></div>{profile && <span className={`tag ${profile.user_confirmed ? 'green' : 'amber'}`}>{profile.user_confirmed ? '已确认' : '待确认'}</span>}</div><p className="panel-description">AI 整理信息，你决定哪些才是事实。</p>
        {!profile ? <div className="empty-state"><span className="empty-symbol"><UiIcon name="shield" /></span><h3>每一份好简历<br />都从真实经历开始</h3><p>先在左侧上传材料或粘贴文字。整理后，你可以在这里核对、补充和修改。</p><div className="empty-note">不确定的内容，留空也没关系。</div></div> : <fieldset disabled={busy} className="facts-form">
          <label className="field-label" htmlFor="person-name">姓名</label><input id="person-name" value={profile.name} onChange={(e) => editProfile({ ...profile, name: e.target.value })} placeholder="填写姓名" />
          {profile.experiences.map((exp, index) => <details className="experience-card" key={index} open><summary><span><span className="experience-number">{String(index + 1).padStart(2, '0')}</span>{exp.name || '待补充的经历'}</span><span>⌄</span></summary><div className="experience-fields">
            <div className="two-fields"><label>经历名称<input aria-label={`经历${index + 1}名称`} value={exp.name} onChange={(e) => editExperience(index, { name: e.target.value })} /></label><label>类型<select aria-label={`经历${index + 1}类型`} value={exp.kind} onChange={(e) => editExperience(index, { kind: e.target.value })}><option value="project">项目</option><option value="internship">工作 / 实习</option><option value="education">教育</option>{!['project', 'internship', 'education'].includes(exp.kind) && <option value={exp.kind}>{exp.kind}</option>}</select></label></div>
            <div className="two-fields"><label>角色<input aria-label={`经历${index + 1}角色`} value={exp.role} onChange={(e) => editExperience(index, { role: e.target.value })} /></label><label>时间<input aria-label={`经历${index + 1}时间`} value={exp.period} onChange={(e) => editExperience(index, { period: e.target.value })} placeholder="如 2025.03—2025.06" /></label></div>
            <label>我做了什么 · 每行一条<textarea aria-label={`经历${index + 1}行动`} rows={3} value={exp.actions.join('\n')} onChange={(e) => editExperience(index, { actions: e.target.value.split('\n') })} /></label>
            <label>真实成果 · 每行一条<textarea aria-label={`经历${index + 1}成果`} rows={2} value={exp.results.join('\n')} onChange={(e) => editExperience(index, { results: e.target.value.split('\n') })} placeholder="没有依据的数字，不必填写" /></label>
            <label>涉及技能 · 每行一项<textarea aria-label={`经历${index + 1}技能`} rows={2} value={exp.skills.join('\n')} onChange={(e) => editExperience(index, { skills: e.target.value.split('\n') })} /></label>
            <button className="text-button danger" onClick={() => editProfile({ ...profile, experiences: profile.experiences.filter((_item, i) => i !== index) })}>移除这段经历</button>
          </div></details>)}
          <button className="secondary-button full" onClick={() => editProfile({ ...profile, experiences: [...profile.experiences, emptyExperience()] })}><UiIcon name="plus" />补充一段经历</button>
          <label className="field-label" htmlFor="all-skills">技能清单 · 每行一项</label><textarea id="all-skills" rows={2} value={profile.skills.join('\n')} onChange={(e) => editProfile({ ...profile, skills: e.target.value.split('\n') })} />
          <label className="field-label" htmlFor="education">教育背景 · 每行一条</label><textarea id="education" rows={2} value={profile.education.join('\n')} onChange={(e) => editProfile({ ...profile, education: e.target.value.split('\n') })} />
          <details className="source-details"><summary>查看与修正原始材料</summary><textarea aria-label="原始材料" rows={5} value={profile.raw_text || ''} onChange={(e) => editProfile({ ...profile, raw_text: e.target.value })} /></details>
          <label className="confirmation-check"><input type="checkbox" checked={!!profile.user_confirmed} onChange={(e) => { onProfileChange({ ...profile, user_confirmed: e.target.checked }); resetOutput() }} /><span>我已核对以上内容，确认可用于本次简历生成。</span></label>
        </fieldset>}
        <div className="fact-note"><UiIcon name="shield" /><span>没有依据的经历与成果数字，不写入简历。</span></div><button className="primary-button full generate-button" disabled={busy || !profile?.user_confirmed || !profile.experiences.length || !jdText.trim()} onClick={() => void generate()}><UiIcon name="spark" />{busy ? activity : '根据已确认事实生成简历'}<span>→</span></button><p className="button-hint">{!profile ? '先整理材料，开始这次准备' : !profile.user_confirmed ? '核对并勾选确认后，即可继续' : !jdText.trim() ? '请在左侧补充目标岗位 JD' : '只改写与排序，不新增经历事实'}</p>
      </section>
      <section className="panel preview-panel"><div className="panel-heading"><div><span className="section-kicker">03 / YOUR NEXT OFFER</span><h2>定向简历</h2></div><span className="tag blue">{markdown ? '生成稿' : '待生成'}</span></div><p className="panel-description">让与岗位相关的经历，先被看见。</p>
        {markdown ? <><div className="preview-toolbar"><div className="segmented"><button className={previewMode === 'preview' ? 'selected' : ''} disabled={busy} onClick={() => setPreviewMode('preview')}>预览</button><button className={previewMode === 'edit' ? 'selected' : ''} disabled={busy} onClick={() => setPreviewMode('edit')}>编辑</button></div><span className="muted">Markdown</span></div>{previewMode === 'preview' ? <article className="resume-paper">{markdown.split('\n').map((line, i) => line.startsWith('# ') ? <h2 key={i}>{line.slice(2)}</h2> : line.startsWith('## ') ? <h3 key={i}>{line.slice(3)}</h3> : line.startsWith('### ') ? <h4 key={i}>{line.slice(4)}</h4> : <p className={/^[-*] /.test(line) ? 'resume-bullet' : ''} key={i}>{line || '\u00a0'}</p>)}</article> : <textarea className="markdown-editor" aria-label="编辑简历 Markdown" disabled={busy} value={markdown} onChange={(e) => onMarkdownChange(e.target.value)} />}
          {numberWarnings.length > 0 && <div className="warning-note" role="status"><strong>数字检查：以下内容缺少材料依据</strong><ul>{numberWarnings.map((item, i) => <li key={i}>{item}</li>)}</ul></div>}<p className="field-hint">初稿及手动修改均需人工核对，数字检查不等于事实认证。</p><button className="secondary-button full" disabled={busy || !markdown.trim()} onClick={download}><UiIcon name="download" />下载 Markdown 简历</button></> : <div className="preview-empty"><div className="paper-skeleton"><span className="skeleton-name" /><span className="skeleton-sub" /><div className="skeleton-divider" /><span className="skeleton-title" /><span /><span /><span className="short" /><div className="skeleton-divider" /><span className="skeleton-title" /><span /><span className="short" /></div><h3>你的下一份简历，从这里开始</h3><p>确认经历并填写岗位后，生成结果会显示在这里。</p></div>}
        <div className="export-note">本轮支持 Markdown；Word / PDF 导出待接入。</div>
      </section>
    </div>
    <section className="next-step"><span className="next-icon"><UiIcon name="chat" /></span><div><h3>把简历里的经历，练成面试时的表达</h3><p>生成后，继续准备面试问题与回答要点。</p></div><button className="secondary-button" disabled={busy || !markdown.trim()} onClick={onInterview}>前往面试话术 →</button></section>
  </>
}
