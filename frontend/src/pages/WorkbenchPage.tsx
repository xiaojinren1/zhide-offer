import { useEffect, useRef, useState } from 'react'
import { api, apiErrorMessage } from '../lib/api'
import type { Experience, ResumeProfile } from '../lib/types'
import { UiIcon } from '../components/Brand'
import ResumePreview from './workbench/ResumePreview'
import { changedFacts, confirmedProfile, emptyExperience, factIssues, FILE_ACCEPT, fileError, generatedMarkdown, generationBlock, manualProfile, operationError, parsedProfile, progress } from './workbench/state'
import './workbench/workbench.css'
interface Props {
  sourceText: string; setSourceText: (text: string) => void
  sourceName: string; setSourceName: (name: string) => void
  profile: ResumeProfile | null; onProfileChange: (profile: ResumeProfile | null) => void
  jdText: string; onJdChange: (text: string) => void
  markdown: string; onMarkdownChange: (text: string) => void
  jdKeywords: string[]; busy: boolean; onBusyChange: (busy: boolean) => void; onInterview: () => void
}
const SAMPLE = '陈同学\n某大学，本科，2022.09—2026.06\n求职方向：产品经理\n项目：校园活动报名流程优化，2025.03—2025.06\n角色：项目成员\n负责收集同学的报名反馈，整理重复填报、信息分散等问题，绘制报名流程原型，并与开发同学沟通需求。\n产出：需求文档与流程原型，协助完成反馈整理。\n技能：需求分析、原型设计、用户反馈整理、跨团队协作。'
const SAMPLE_JD = '产品经理（示例岗位）\n工作职责：收集用户需求，分析业务流程，完成产品原型与需求文档，与研发团队沟通并推动方案落地。\n岗位要求：具备需求分析、原型设计和沟通协作能力，有校园项目或实习经历。'
export default function WorkbenchPage({ sourceText, setSourceText, sourceName, setSourceName, profile, onProfileChange, jdText, onJdChange, markdown, onMarkdownChange, jdKeywords, busy, onBusyChange, onInterview }: Props) {
  const [activity, setActivity] = useState('')
  const [error, setError] = useState('')
  const [numberWarnings, setNumberWarnings] = useState<string[]>([])
  const [previewMode, setPreviewMode] = useState<'preview' | 'edit'>('preview')
  const [retryAction, setRetryAction] = useState<'parse' | 'generate' | null>(null)
  const [waiting, setWaiting] = useState(false)
  const [memoryBusy, setMemoryBusy] = useState(false)
  const [memoryMessage, setMemoryMessage] = useState('')
  const [manuallyEdited, setManuallyEdited] = useState(false)
  const requestLock = useRef(false)
  const lastFile = useRef<File | undefined>(undefined)
  const mounted = useRef(true)
  const snapshot = JSON.stringify([sourceText, sourceName, profile, jdText, markdown, jdKeywords])
  const latestInput = useRef(snapshot)
  latestInput.current = snapshot
  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false }
  }, [])
  useEffect(() => {
    if (!activity) return
    const timer = window.setTimeout(() => setWaiting(true), 15000)
    return () => window.clearTimeout(timer)
  }, [activity])
  const current = progress(profile, jdText, markdown)
  const blocked = generationBlock(profile, jdText)
  const issues = profile ? factIssues(profile) : []
  const resetOutput = () => { setNumberWarnings([]); setError(''); setRetryAction(null); setManuallyEdited(false) }
  const invalidateDraft = () => { onMarkdownChange(''); resetOutput() }
  const editProfile = (value: ResumeProfile) => { onProfileChange(changedFacts(value)); invalidateDraft() }
  const editJd = (text: string) => {
    onJdChange(text)
    if (profile) onProfileChange(changedFacts(profile))
    invalidateDraft()
  }
  const editSource = (text: string) => {
    setSourceText(text); setSourceName(''); lastFile.current = undefined
    onProfileChange(null); invalidateDraft()
  }
  const startManual = () => {
    if (busy || requestLock.current || profile) return
    onProfileChange(manualProfile(sourceText)); invalidateDraft()
  }
  const confirmFacts = (checked: boolean) => {
    if (busy || requestLock.current || !profile) return
    try {
      onProfileChange(checked ? confirmedProfile(profile) : changedFacts(profile)); invalidateDraft()
    } catch (reason) { setError(operationError(reason)) }
  }
  const saveMemory = async () => {
    if (busy || requestLock.current || memoryBusy || !profile || !profile.user_confirmed || issues.length > 0) return
    setMemoryBusy(true); setMemoryMessage('')
    try {
      const result = await api.saveProfile(profile.name || sourceName || '未命名经历库', { ...profile, user_confirmed: true })
      if (!result.ok) throw new Error(result.error || '保存经历库失败，请重试。')
      setMemoryMessage('经历已保存到个人记忆，可从左侧“个人记忆”查看。')
    } catch (cause) {
      setMemoryMessage(apiErrorMessage(cause))
    } finally {
      setMemoryBusy(false)
    }
  }
  const editExperience = (index: number, patch: Partial<Experience>) => {
    if (profile) editProfile({ ...profile, experiences: profile.experiences.map((item, i) => i === index ? { ...item, ...patch } : item) })
  }
  const parse = async (file?: File) => {
    if (busy || requestLock.current || (!file && !sourceText.trim())) return
    if (file) {
      const message = fileError(file)
      if (message) { setError(message); setRetryAction(null); return }
    }
    lastFile.current = file
    requestLock.current = true
    invalidateDraft(); setSourceName(''); onBusyChange(true); setWaiting(false); setActivity('正在整理材料…'); onProfileChange(null)
    const expected = JSON.stringify([sourceText, '', null, jdText, '', jdKeywords])
    latestInput.current = expected
    try {
      const result = file ? await api.parseResumeFile(file) : await api.parseResumeText(sourceText)
      if (!mounted.current || latestInput.current !== expected) return
      const parsed = parsedProfile(result)
      onProfileChange(parsed)
      setSourceText((typeof result.raw_text === 'string' && result.raw_text) || parsed.raw_text || sourceText)
      setSourceName(file?.name || '文本材料')
    } catch (err) { if (mounted.current && latestInput.current === expected) { setError(operationError(err)); setRetryAction('parse') } }
    finally { requestLock.current = false; if (mounted.current) { onBusyChange(false); setActivity(''); setWaiting(false) } }
  }
  const generate = async () => {
    if (busy || requestLock.current || !profile || generationBlock(profile, jdText)) return
    requestLock.current = true
    invalidateDraft(); onBusyChange(true); setWaiting(false); setActivity('正在生成并检查简历…')
    const expected = JSON.stringify([sourceText, sourceName, profile, jdText, '', jdKeywords])
    latestInput.current = expected
    try {
      const result = await api.generateResume(jdText, profile, jdKeywords)
      if (!mounted.current || latestInput.current !== expected) return
      onMarkdownChange(generatedMarkdown(result)); setNumberWarnings(Array.isArray(result.untraceable) ? result.untraceable.filter((item) => typeof item === 'string') : []); setPreviewMode('preview')
    } catch (err) { if (mounted.current && latestInput.current === expected) { setError(operationError(err)); setRetryAction('generate') } }
    finally { requestLock.current = false; if (mounted.current) { onBusyChange(false); setActivity(''); setWaiting(false) } }
  }
  const download = () => {
    const url = URL.createObjectURL(new Blob([markdown], { type: 'text/markdown;charset=utf-8' }))
    const a = document.createElement('a'); a.href = url; a.download = `${profile?.name || '职得offer'}-定向简历.md`; a.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  const editMarkdown = (text: string) => {
    onMarkdownChange(text); setNumberWarnings([]); setManuallyEdited(true)
  }
  return <div className="role-b-workbench" aria-busy={busy}>
    <ol className="stepper" aria-label="求职准备进度">{['材料输入', '确认事实', '岗位 JD', '简历预览'].map((name, i) => <li key={name} aria-current={current.step === i + 1 ? 'step' : undefined} className={current.step === i + 1 ? 'current' : current.step > i + 1 ? 'complete' : ''}><a href={`#wb-step-${i + 1}`}><span className="step-number">{current.step > i + 1 ? <UiIcon name="check" /> : i + 1}</span><span>{name}</span></a>{i < 3 && <span className="step-line" />}</li>)}</ol>
    <div className="wb-status" role="status"><strong>当前：{current.label}</strong><p>{blocked || (markdown.trim() ? '简历已生成，请逐句核对后下载。' : '事实与岗位已就绪，可以生成简历。')}</p></div>
    <p className="wb-hint">离开前请确认页面上方显示工作台已保存；原始上传文件不会留存。演示材料完全虚构，请替换为自己的真实经历。</p>
    {error && <div className="error-banner" role="alert"><strong>这一步没有完成</strong><span>{error}</span>{retryAction && <button className="secondary-button" disabled={busy} onClick={() => retryAction === 'parse' ? void parse(lastFile.current) : void generate()}>重试{retryAction === 'parse' ? '整理材料' : '生成简历'}</button>}<button className="wb-dismiss" onClick={() => setError('')} aria-label="关闭错误提示">×</button></div>}
    {busy && <div className="activity-banner" role="status"><span className="spinner" />{activity || '正在处理…'}<span className="muted">{waiting ? '模型仍在处理，请勿重复提交；若超时会显示重试入口。' : '完成后可继续编辑，请勿刷新页面。'}</span></div>}
    <div className="workbench-grid">
      <section id="wb-step-1" tabIndex={-1} className="panel materials-panel"><div className="panel-heading"><div><span className="section-kicker">01 / MATERIALS</span><h2>求职材料</h2></div><UiIcon name="folder" /></div><fieldset disabled={busy}>
        <label className="upload-zone"><input aria-label="上传求职材料" type="file" accept={FILE_ACCEPT} onChange={(e) => { const file = e.target.files?.[0]; if (file) void parse(file); e.target.value = '' }} /><span className="upload-icon"><UiIcon name="upload" /></span><strong>上传简历或经历材料</strong><span>DOCX · 文字 PDF · TXT · Markdown</span></label>
        <p className="wb-hint">单文件不超过 10 MB。暂不支持图片、语音、旧版 DOC 和扫描 PDF 的 OCR；可先转为文字再粘贴。</p>
        {sourceName && <div className="source-chip"><UiIcon name="file" /><span>{sourceName}</span><span className="tag blue">已整理</span></div>}
        <div className="field-heading"><label htmlFor="source-text">或粘贴你的经历</label><button className="text-button" onClick={() => { editSource(SAMPLE); onJdChange(SAMPLE_JD) }}>填入演示材料</button></div>
        <textarea id="source-text" className="source-text" value={sourceText} placeholder="项目、实习、工作或校园经历都可以。先写清你做过什么，无需提前润色。" onChange={(e) => editSource(e.target.value)} />
        <button className="secondary-button full" disabled={!sourceText.trim()} onClick={() => void parse()}><UiIcon name="spark" />{activity === '正在整理材料…' ? activity : profile ? '重新整理文本材料' : '整理文本材料'}</button>
        <p className="wb-hint">重新整理会清空当前事实确认和生成稿。材料只用于整理，请勿填写无依据的经历与数字。</p>
        {!profile && <div className="manual-entry"><p className="wb-hint">不想使用 AI 整理，或解析失败？可以直接填写自己的真实经历。手工录入无需模型，生成简历仍需模型服务。</p><button className="secondary-button full" onClick={startManual}>直接手工填写事实</button></div>}
      </fieldset></section>
      <section id="wb-step-2" tabIndex={-1} className="panel facts-panel"><div className="panel-heading"><div><span className="section-kicker">02 / YOUR STORY</span><h2>关键事实，先由你确认</h2></div>{profile && <span className={`tag ${profile.user_confirmed && !issues.length ? 'green' : 'amber'}`}>{profile.user_confirmed && !issues.length ? '已确认' : '待确认'}</span>}</div><p className="panel-description">AI 整理信息，你决定哪些才是事实。也可直接手工填写，无需先调用 AI。</p>
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
          <details className="source-details"><summary>查看与修正原始材料</summary><textarea aria-label="原始材料" rows={5} value={sourceText} onChange={(e) => { setSourceText(e.target.value); setSourceName(''); lastFile.current = undefined; editProfile({ ...profile, raw_text: e.target.value }) }} /><p className="wb-hint">修改会同步材料区、撤销确认并清空旧稿，但不会自动改写上述事实。请人工核对，或回到第 1 步重新整理。</p></details>
          {issues.length > 0 && <div id="wb-fact-issues" className="warning-note" role="status"><strong>确认前请补充</strong><ul>{issues.map((issue) => <li key={issue}>{issue}</li>)}</ul></div>}
          <label className="confirmation-check"><input type="checkbox" aria-describedby={issues.length ? 'wb-fact-issues' : undefined} disabled={issues.length > 0 && !profile.user_confirmed} checked={!!profile.user_confirmed && !issues.length} onChange={(e) => { confirmFacts(e.target.checked); setMemoryMessage('') }} /><span>我已核对以上内容，确认可用于本次简历生成。</span></label>
          {profile.user_confirmed && !issues.length && <div className="memory-save-row"><button type="button" className="secondary-button" disabled={busy || memoryBusy} onClick={() => void saveMemory()}>{memoryBusy ? '保存中…' : '保存到个人记忆'}</button>{memoryMessage && <span className="field-hint" role="status">{memoryMessage}</span>}</div>}
        </fieldset>}
        <div className="fact-note"><UiIcon name="shield" /><span>没有依据的经历与成果数字，不写入简历。修改事实或岗位 JD 后，需要重新确认。</span></div>
      </section>
      <section id="wb-step-3" tabIndex={-1} className="panel wb-jd-panel"><div className="panel-heading"><div><span className="section-kicker">03 / TARGET ROLE</span><h2>目标岗位 JD</h2></div><span className={`tag ${jdText.trim() ? 'green' : 'amber'}`}>{jdText.trim() ? '已填写' : '待填写'}</span></div><fieldset disabled={busy}><label className="field-label" htmlFor="jd-text">岗位职责与任职要求 <span>不限岗位</span></label><textarea id="jd-text" className="jd-text" value={jdText} onChange={(e) => editJd(e.target.value)} placeholder="粘贴完整岗位职责和任职要求，让每次生成都针对具体岗位。" /><p className="wb-hint">可提前填写。修改 JD 会撤销事实确认并清空旧简历，请回到第 2 步重新确认。</p></fieldset></section>
      <section id="wb-step-4" tabIndex={-1} className="panel preview-panel"><div className="panel-heading"><div><span className="section-kicker">04 / YOUR NEXT OFFER</span><h2>定向简历预览</h2></div><span className="tag blue">{markdown ? '已生成' : '待生成'}</span></div><p className="panel-description">让与岗位相关的经历，先被看见。</p>
        <button className="primary-button full generate-button" disabled={busy || Boolean(blocked)} onClick={() => void generate()}><UiIcon name="spark" />{activity === '正在生成并检查简历…' ? activity : markdown ? '重新生成简历' : '根据已确认事实生成简历'}</button><p className="wb-hint">{blocked || (markdown ? '重新生成将替换当前稿件，包括手动修改；如需保留请先下载。' : '只改写与排序，不新增经历事实。')}</p>
        {markdown && (blocked ? <p className="warning-note" role="status">以下是保留的草稿，尚不能作为当前已确认结果。请补全事实与岗位、重新确认后生成。</p> : <p className="wb-success" role="status">简历已生成，可预览、编辑并下载 Markdown。</p>)}
        {markdown ? <><div className="preview-toolbar"><div className="segmented"><button className={previewMode === 'preview' ? 'selected' : ''} disabled={busy} onClick={() => setPreviewMode('preview')}>预览</button><button className={previewMode === 'edit' ? 'selected' : ''} disabled={busy} onClick={() => setPreviewMode('edit')}>编辑</button></div><span className="muted">Markdown</span></div>{previewMode === 'preview' ? <ResumePreview markdown={markdown} /> : <textarea className="markdown-editor" aria-label="编辑简历 Markdown" disabled={busy} value={markdown} onChange={(e) => editMarkdown(e.target.value)} />}
          {manuallyEdited && <p className="warning-note">稿件已手动修改，原数字检查不再代表当前内容，请重新核对所有事实和数字。</p>}
          {numberWarnings.length > 0 && <div className="warning-note" role="status"><strong>数字检查：以下内容缺少材料依据</strong><ul>{numberWarnings.map((item, i) => <li key={i}>{item}</li>)}</ul></div>}<p className="field-hint">初稿及手动修改均需人工核对，数字检查不等于事实认证。</p><button className="secondary-button full" disabled={busy || !markdown.trim()} onClick={download}><UiIcon name="download" />下载 Markdown 简历</button></> : <div className="preview-empty"><div className="paper-skeleton"><span className="skeleton-name" /><span className="skeleton-sub" /><div className="skeleton-divider" /><span className="skeleton-title" /><span /><span /><span className="short" /><div className="skeleton-divider" /><span className="skeleton-title" /><span /><span className="short" /></div><h3>你的下一份简历，从这里开始</h3><p>确认经历并填写岗位后，生成结果会显示在这里。</p></div>}
        <div className="export-note">本轮支持 Markdown；Word 可在个人记忆页导出，PDF 暂不支持。</div>
      </section>
    </div>
    <section className="next-step"><span className="next-icon"><UiIcon name="chat" /></span><div><h3>把简历里的经历，练成面试时的表达</h3><p>生成后，继续准备面试问题与回答要点。</p></div><button className="secondary-button" disabled={busy || !markdown.trim()} onClick={onInterview}>前往面试话术 →</button></section>
  </div>
}
