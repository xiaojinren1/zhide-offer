import { useEffect, useRef, useState } from 'react'
import ImportReview from './library/ImportReview'
import './library/library.css'
import { api } from '../lib/api'
import type { Experience, ResumeProfile } from '../lib/types'
import { UiIcon } from '../components/Brand'
import ResumePreview from './workbench/ResumePreview'
import RoleRequirementsEditor from './workbench/RoleRequirementsEditor'
import DiagnosePage from './DiagnosePage'
import QualityPage from './QualityPage'
import { changedFacts, confirmedProfile, emptyExperience, factIssues, FILE_ACCEPT, fileError, generatedMarkdown, generationBlock, generationReview, manualProfile, operationError, parsedProfile, progress } from './workbench/state'
import type { GenerationReview } from './workbench/state'
import { tailoringReport } from '../lib/tailoring'
import type { TailoringReport } from '../lib/tailoring'
import './workbench/workbench.css'
interface Props {
  userId?: string
  initialStep?: 3 | 4
  sourceText: string; setSourceText: (text: string) => void
  sourceName: string; setSourceName: (name: string) => void
  profile: ResumeProfile | null; onProfileChange: (profile: ResumeProfile | null) => void
  jdText: string; onJdChange: (text: string) => void
  markdown: string; onMarkdownChange: (text: string) => void
  jdKeywords: string[]; onJdKeywordsChange?: (keywords: string[]) => void; busy: boolean; onBusyChange: (busy: boolean) => void; onDiagnose?: () => void; onQuality?: () => void; onInterview?: () => void
}
const SAMPLE = '陈同学\n某大学，本科，2022.09—2026.06\n求职方向：产品经理\n项目：校园活动报名流程优化，2025.03—2025.06\n角色：项目成员\n负责收集同学的报名反馈，整理重复填报、信息分散等问题，绘制报名流程原型，并与开发同学沟通需求。\n产出：需求文档与流程原型，协助完成反馈整理。\n技能：需求分析、原型设计、用户反馈整理、跨团队协作。'
const SAMPLE_JD = '产品经理（示例岗位）\n工作职责：收集用户需求，分析业务流程，完成产品原型与需求文档，与研发团队沟通并推动方案落地。\n岗位要求：具备需求分析、原型设计和沟通协作能力，有校园项目或实习经历。'
export default function WorkbenchPage({ userId, initialStep = 3, sourceText, setSourceText, sourceName, setSourceName, profile, onProfileChange, jdText, onJdChange, markdown, onMarkdownChange, jdKeywords, onJdKeywordsChange, busy, onBusyChange, onDiagnose, onQuality, onInterview }: Props) {
  // 保留旧调用方的可选参数，避免队友页面或测试在联调时因接口变化中断。
  void onDiagnose; void onQuality
  const [activity, setActivity] = useState('')
  const [error, setError] = useState('')
  const [generationCheck, setGenerationCheck] = useState<{ snapshot: string; review: GenerationReview; numbers: string[]; tailoring: TailoringReport | null } | null>(null)
  const [previewMode, setPreviewMode] = useState<'preview' | 'edit'>('preview')
  const [retryAction, setRetryAction] = useState<'parse' | 'generate' | null>(null)
  const [waiting, setWaiting] = useState(false)
  const [activeStep, setActiveStep] = useState(markdown.trim() ? (initialStep === 4 && profile?.user_confirmed && !factIssues(profile).length ? 4 : 3) : profile ? 2 : 1)
  const [optimizationTool, setOptimizationTool] = useState<'quality' | 'match'>('quality')
  const [initialDraft, setInitialDraft] = useState(false)
  const [manuallyEdited, setManuallyEdited] = useState(false)
  const requestLock = useRef(false)
  const initialGeneration = useRef(false)
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
  const activeCheck = generationCheck?.snapshot === snapshot && !manuallyEdited ? generationCheck : null
  const review = activeCheck?.review || generationReview(null)
  const numberWarnings = activeCheck?.numbers || []
  const tailoring = activeCheck?.tailoring
  const tailoringNeedsReview = !tailoring || tailoring.unsupported_claims.length > 0
    || tailoring.requirements.some((item) => item.status === 'supported' && !item.output_excerpt)
  const resetOutput = () => { setGenerationCheck(null); setError(''); setRetryAction(null); setManuallyEdited(false) }
  const invalidateDraft = () => { onMarkdownChange(''); resetOutput() }
  const editProfile = (value: ResumeProfile) => { onProfileChange(changedFacts({...value,experiences:value.experiences.map(e=>e.kind==='education'?{...e,actions:[],results:[],skills:[]}:e)})); invalidateDraft() }
  const editJd = (text: string) => {
    onJdChange(text)
    resetOutput()
  }
  const editSource = (text: string) => {
    setSourceText(text); setSourceName(''); lastFile.current = undefined
    onProfileChange(null); invalidateDraft()
  }
  const clearMaterial = () => {
    if (busy || requestLock.current) return
    editSource(''); setActiveStep(1)
  }
  const removeMaterial = () => {
    if (busy || requestLock.current) return
    if (window.confirm(`确定从当前工作台移除“${sourceName}”吗？\n同时清除材料文本、解析事实和当前简历稿，保留岗位 JD 及已存入经历库的卡片。`)) clearMaterial()
  }
  const startManual = () => {
    if (busy || requestLock.current || profile) return
    onProfileChange(manualProfile(sourceText)); invalidateDraft()
    setActiveStep(2)
  }
  const confirmFacts = (checked: boolean) => {
    if (busy || requestLock.current || !profile) return
    try {
      onProfileChange(checked ? confirmedProfile(profile) : changedFacts(profile)); invalidateDraft()
    } catch (reason) { setError(operationError(reason)) }
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
      const result = file
        ? (/\.(png|jpe?g|webp)$/i.test(file.name) ? await api.parseResumeImage(file) : await api.parseResumeFile(file))
        : await api.parseResumeText(sourceText)
      if (!mounted.current || latestInput.current !== expected) return
      const parsed = parsedProfile(result)
      onProfileChange(parsed)
      setSourceText((typeof result.raw_text === 'string' && result.raw_text) || parsed.raw_text || sourceText)
      setSourceName(file?.name || '文本材料')
      setActiveStep(2)
    } catch (err) { if (mounted.current && latestInput.current === expected) { setError(operationError(err)); setRetryAction('parse') } }
    finally { requestLock.current = false; if (mounted.current) { onBusyChange(false); setActivity(''); setWaiting(false) } }
  }
  const generate = async (initial = false) => {
    if (busy || requestLock.current || !profile || generationBlock(profile, jdText)) return
    requestLock.current = true
    initialGeneration.current = initial
    invalidateDraft(); onBusyChange(true); setWaiting(false); setActivity('正在生成并检查简历…')
    const expected = JSON.stringify([sourceText, sourceName, profile, jdText, '', jdKeywords])
    latestInput.current = expected
    try {
      const result = await api.generateResume(initial ? '' : jdText, profile, initial ? [] : jdKeywords)
      if (!mounted.current || latestInput.current !== expected) return
      const nextMarkdown = generatedMarkdown(result)
      onMarkdownChange(nextMarkdown)
      setInitialDraft(initial || !jdText.trim())
      setGenerationCheck({ snapshot: JSON.stringify([sourceText, sourceName, profile, jdText, nextMarkdown, jdKeywords]), review: generationReview(result), numbers: Array.isArray(result.untraceable) ? result.untraceable.filter((item) => typeof item === 'string') : [], tailoring: tailoringReport(result.tailoring, profile, jdText, nextMarkdown) })
      setPreviewMode('preview')
      setActiveStep(3)
    } catch (err) { if (mounted.current && latestInput.current === expected) { setError(operationError(err)); setRetryAction('generate') } }
    finally { requestLock.current = false; if (mounted.current) { onBusyChange(false); setActivity(''); setWaiting(false) } }
  }
  const download = () => {
    const url = URL.createObjectURL(new Blob([markdown], { type: 'text/markdown;charset=utf-8' }))
    const a = document.createElement('a'); a.href = url; a.download = `${profile?.name || '职得offer'}-定向简历.md`; a.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  const editMarkdown = (text: string) => {
    onMarkdownChange(text); setGenerationCheck(null); setManuallyEdited(true)
  }
  const stepReady = (step: number) => {
    if (step === 2) return Boolean(profile)
    if (step === 3 || step === 4) return Boolean(profile?.user_confirmed && !issues.length && markdown.trim())
    return true
  }
  const canVisitStep = (step: number) => stepReady(step)
  const stepActions = (step: number) => <div className="step-actions">
    {step === 1 && <button type="button" className="secondary-button" disabled={busy || (!sourceText && !sourceName && !profile && !markdown)} onClick={clearMaterial}>清除文本</button>}
    {step > 1 && <button type="button" className="secondary-button" disabled={busy} onClick={() => setActiveStep(step - 1)}>上一步</button>}
    {step === 1 && <button type="button" className="primary-button" disabled={busy || !stepReady(2)} onClick={() => setActiveStep(2)}>下一步：确认事实</button>}
    {step === 2 && <button type="button" className="primary-button" disabled={busy || Boolean(blocked)} onClick={() => markdown.trim() ? setActiveStep(3) : void generate(true)}>{markdown.trim() ? '继续检查与优化' : '生成初稿并继续'}</button>}
    {step === 3 && <button type="button" className="primary-button" disabled={busy || !stepReady(4)} onClick={() => setActiveStep(4)}>查看最终简历</button>}
  </div>
  return <div className="role-b-workbench" aria-busy={busy}>
    <ol className="stepper" aria-label="求职准备进度">{['材料输入', '确认事实', '检查与优化', '简历预览'].map((name, i) => <li key={name} aria-current={activeStep === i + 1 ? 'step' : undefined} className={activeStep === i + 1 ? 'current' : current.step > i + 1 ? 'complete' : ''}><button type="button" className="step-link" disabled={busy || !canVisitStep(i + 1)} aria-disabled={busy || !canVisitStep(i + 1)} onClick={() => !busy && canVisitStep(i + 1) && setActiveStep(i + 1)}><span className="step-number">{current.step > i + 1 ? <UiIcon name="check" /> : i + 1}</span><span>{name}</span></button><a className="step-link-legacy" href={`#wb-step-${i + 1}`} hidden aria-hidden="true" tabIndex={-1}>{name}</a>{i < 3 && <span className="step-line" />}</li>)}</ol>
    <div className="wb-status" role="status"><strong>当前：{current.label}</strong><p>{blocked || (markdown.trim() ? '围绕当前简历反复检查和修改；满意后查看最终简历。' : '事实已确认，可先生成初稿，再填写岗位并检查优化。')}</p></div>
    <p className="wb-hint">离开前请确认页面上方显示工作台已保存；原始上传文件不会留存。演示材料完全虚构，请替换为自己的真实经历。</p>
    {error && <div className="error-banner" role="alert"><strong>这一步没有完成</strong><span>{error}</span>{retryAction && <button className="secondary-button" disabled={busy} onClick={() => retryAction === 'parse' ? void parse(lastFile.current) : void generate(initialGeneration.current)}>重试{retryAction === 'parse' ? '整理材料' : '生成简历'}</button>}<button className="wb-dismiss" onClick={() => setError('')} aria-label="关闭错误提示">×</button></div>}
    {busy && <div className="activity-banner" role="status"><span className="spinner" />{activity || '正在处理…'}<span className="muted">{waiting ? '模型仍在处理，请勿重复提交；若超时会显示重试入口。' : '完成后可继续编辑，请勿刷新页面。'}</span></div>}
    <div className="workbench-grid step-page-grid">
      <section id="wb-step-1" hidden={activeStep !== 1} aria-hidden={activeStep !== 1} tabIndex={-1} className="panel materials-panel"><div className="panel-heading"><div><span className="section-kicker">01 / MATERIALS</span><h2>求职材料</h2></div><UiIcon name="folder" /></div><fieldset disabled={busy}>
        <label className="upload-zone"><input aria-label="上传求职材料" type="file" accept={FILE_ACCEPT} onChange={(e) => { const file = e.target.files?.[0]; if (file) void parse(file); e.target.value = '' }} /><span className="upload-icon"><UiIcon name="upload" /></span><strong>上传简历或经历材料</strong><span>DOCX · 文字 PDF · TXT · Markdown · JPG/PNG/WebP</span></label>
        <p className="wb-hint">单文件不超过 10 MB。图片会交给视觉模型整理，结果仍需你逐项确认；语音、旧版 DOC 和扫描 PDF 的 OCR 尚未接入。</p>
        {sourceName && <div className="source-chip"><UiIcon name="file" /><span>{sourceName}</span><span className="tag blue">已整理</span><button type="button" className="source-remove" aria-label={`移除材料：${sourceName}`} title="移除材料" onClick={removeMaterial}>×</button></div>}
        <div className="field-heading"><label htmlFor="source-text">或粘贴你的经历</label><button className="text-button" onClick={() => { editSource(SAMPLE); onJdChange(SAMPLE_JD) }}>填入演示材料</button></div>
        <textarea id="source-text" className="source-text" value={sourceText} placeholder="项目、实习、工作或校园经历都可以。先写清你做过什么，无需提前润色。" onChange={(e) => editSource(e.target.value)} />
        <button className="secondary-button full" disabled={!sourceText.trim()} onClick={() => void parse()}><UiIcon name="spark" />{activity === '正在整理材料…' ? activity : profile ? '重新整理文本材料' : '整理文本材料'}</button>
        <p className="wb-hint">重新整理会清空当前事实确认和生成稿。材料只用于整理，请勿填写无依据的经历与数字。</p>
        {!profile && <div className="manual-entry"><p className="wb-hint">不想使用 AI 整理，或解析失败？可以直接填写自己的真实经历。手工录入无需模型，生成简历仍需模型服务。</p><button className="secondary-button full" onClick={startManual}>直接手工填写事实</button></div>}
      </fieldset>{stepActions(1)}</section>
      <section id="wb-step-2" hidden={activeStep !== 2} aria-hidden={activeStep !== 2} tabIndex={-1} className="panel facts-panel"><div className="panel-heading"><div><span className="section-kicker">02 / YOUR STORY</span><h2>关键事实，先由你确认</h2></div>{profile && <span className={`tag ${profile.user_confirmed && !issues.length ? 'green' : 'amber'}`}>{profile.user_confirmed && !issues.length ? '已确认' : '待确认'}</span>}</div><p className="panel-description">AI 整理信息，你决定哪些才是事实。也可直接手工填写，无需先调用 AI。</p>
        {!profile ? <div className="empty-state"><span className="empty-symbol"><UiIcon name="shield" /></span><h3>每一份好简历<br />都从真实经历开始</h3><p>先在左侧上传材料或粘贴文字。整理后，你可以在这里核对、补充和修改。</p><div className="empty-note">不确定的内容，留空也没关系。</div></div> : <fieldset disabled={busy} className="facts-form">
          <label className="field-label" htmlFor="person-name">姓名</label><input id="person-name" value={profile.name} onChange={(e) => editProfile({ ...profile, name: e.target.value })} placeholder="填写姓名" />
          {profile.experiences.map((exp, index) => <details className="experience-card" key={index} open><summary><span><span className="experience-number">{String(index + 1).padStart(2, '0')}</span>{exp.name || '待补充的经历'}</span><span>⌄</span></summary><div className="experience-fields">
            <div className="two-fields"><label>经历名称<input aria-label={`经历${index + 1}名称`} value={exp.name} onChange={(e) => editExperience(index, { name: e.target.value })} /></label><label>类型<select aria-label={`经历${index + 1}类型`} value={exp.kind} onChange={(e) => editExperience(index, { kind: e.target.value })}><option value="project">项目</option><option value="internship">工作 / 实习</option><option value="education">教育</option>{!['project', 'internship', 'education'].includes(exp.kind) && <option value={exp.kind}>{exp.kind}</option>}</select></label></div>
            {exp.kind === 'education' && <p className="wb-hint">教育仅记录学校、专业学历和起止时间，不添加描述。</p>}
            <div className="two-fields"><label>{exp.kind === 'education' ? '专业 / 学历' : '角色'}<input aria-label={`经历${index + 1}角色`} value={exp.role} onChange={(e) => editExperience(index, { role: e.target.value })} /></label><label>时间<input aria-label={`经历${index + 1}时间`} value={exp.period} onChange={(e) => editExperience(index, { period: e.target.value })} placeholder="如 2025.03—2025.06" /></label></div>
            {exp.kind !== 'education' && <><label>我做了什么 · 每行一条<textarea aria-label={`经历${index + 1}行动`} rows={3} value={exp.actions.join('\n')} onChange={(e) => editExperience(index, { actions: e.target.value.split('\n') })} /></label>
            <label>真实成果 · 每行一条<textarea aria-label={`经历${index + 1}成果`} rows={2} value={exp.results.join('\n')} onChange={(e) => editExperience(index, { results: e.target.value.split('\n') })} placeholder="没有依据的数字，不必填写" /></label>
            <label>涉及技能 · 每行一项<textarea aria-label={`经历${index + 1}技能`} rows={2} value={exp.skills.join('\n')} onChange={(e) => editExperience(index, { skills: e.target.value.split('\n') })} /></label></>}
            <button className="text-button danger" onClick={() => editProfile({ ...profile, experiences: profile.experiences.filter((_item, i) => i !== index) })}>移除这段经历</button>
          </div></details>)}
          <button className="secondary-button full" onClick={() => editProfile({ ...profile, experiences: [...profile.experiences, emptyExperience()] })}><UiIcon name="plus" />补充一段经历</button>
          <label className="field-label" htmlFor="all-skills">技能清单 · 每行一项</label><textarea id="all-skills" rows={2} value={profile.skills.join('\n')} onChange={(e) => editProfile({ ...profile, skills: e.target.value.split('\n') })} />
          {!!profile.education.length && <p className="warning-note">旧教育文本：{profile.education.join('；')}。请在教育卡中核对学校、专业学历和时间；此文本仅作来源参考。</p>}
          <details className="source-details"><summary>查看与修正原始材料</summary><textarea aria-label="原始材料" rows={5} value={sourceText} onChange={(e) => { setSourceText(e.target.value); setSourceName(''); lastFile.current = undefined; editProfile({ ...profile, raw_text: e.target.value }) }} /><p className="wb-hint">修改会同步材料区、撤销确认并清空旧稿，但不会自动改写上述事实。请人工核对，或回到第 1 步重新整理。</p></details>
          {issues.length > 0 && <div id="wb-fact-issues" className="warning-note" role="status"><strong>确认前请补充</strong><ul>{issues.map((issue) => <li key={issue}>{issue}</li>)}</ul></div>}
          <label className="confirmation-check"><input type="checkbox" aria-describedby={issues.length ? 'wb-fact-issues' : undefined} disabled={issues.length > 0 && !profile.user_confirmed} checked={!!profile.user_confirmed && !issues.length} onChange={(e) => { confirmFacts(e.target.checked) }} /><span>我已核对以上内容，确认可用于本次简历生成。</span></label>

        </fieldset>}
        {profile && userId && <ImportReview key={JSON.stringify([userId,profile,sourceName])} material={{expected_user_id:userId,profile,source_name:sourceName||'工作台材料'}} disabled={busy||!profile.user_confirmed||issues.length>0}/> }
        <div className="fact-note"><UiIcon name="shield" /><span>没有依据的经历与成果数字，不写入简历。修改真实事实后需要重新确认；岗位要求可在下一步补充。</span></div>{stepActions(2)}
      </section>
      <section id="wb-step-3" hidden={activeStep !== 3} aria-hidden={activeStep !== 3} tabIndex={-1} className="panel wb-jd-panel"><div className="panel-heading"><div><span className="section-kicker">03 / REFINE YOUR RESUME</span><h2>检查与优化</h2></div><span className="tag blue">当前稿持续更新</span></div><p className="panel-description">补充岗位要求，检查简历并采纳建议。可以反复修改和检查，满意后再预览。</p><fieldset disabled={busy}><RoleRequirementsEditor id="jd-text" jdText={jdText} onChange={editJd} disabled={busy} onBusyChange={onBusyChange} /><p className="wb-hint">修改岗位要求保留当前简历和事实确认，原报告需重新运行；岗位缺口不能写成个人经历。</p></fieldset>
        <div className="optimization-tools" role="group" aria-label="选择优化工具"><button type="button" className={optimizationTool === 'quality' ? 'primary-button' : 'secondary-button'} disabled={busy} aria-pressed={optimizationTool === 'quality'} onClick={() => setOptimizationTool('quality')}>简历检查</button><button type="button" className={optimizationTool === 'match' ? 'primary-button' : 'secondary-button'} disabled={busy} aria-pressed={optimizationTool === 'match'} onClick={() => setOptimizationTool('match')}>岗位匹配</button></div>
        {activeStep === 3 && optimizationTool === 'quality' && <QualityPage embedded jdText={jdText} jdKeywords={jdKeywords} profile={profile} markdown={markdown} onMarkdownChange={editMarkdown} busy={busy} onBusyChange={onBusyChange} />}
        {activeStep === 3 && optimizationTool === 'match' && <DiagnosePage embedded jdText={jdText} setJdText={editJd} profile={profile} markdown={markdown} onMarkdownChange={editMarkdown} busy={busy} onBusyChange={onBusyChange} onDone={(_text, keywords) => onJdKeywordsChange?.(keywords)} />}
        <details className="optimization-draft" open><summary>查看与编辑当前简历</summary><p className="wb-hint">采纳建议会更新此稿；手动编辑后请重新检查。原始事实没有变化时，无需返回确认。</p><textarea className="markdown-editor" aria-label="优化阶段编辑简历" disabled={busy} value={markdown} onChange={e => editMarkdown(e.target.value)} /></details>{stepActions(3)}</section>
      <section id="wb-step-4" hidden={activeStep !== 4} aria-hidden={activeStep !== 4} tabIndex={-1} className="panel preview-panel"><div className="panel-heading"><div><span className="section-kicker">04 / YOUR NEXT OFFER</span><h2>简历预览</h2></div><span className={`tag ${markdown && review.warning ? 'amber' : 'blue'}`}>{markdown ? '草稿待核对' : '待生成'}</span></div><p className="panel-description">让与岗位相关的经历，先被看见。</p>
        <button className="primary-button full generate-button" disabled={busy || Boolean(blocked)} onClick={() => void generate()}><UiIcon name="spark" />{activity === '正在生成并检查简历…' ? activity : markdown ? '重新生成简历' : '根据已确认事实生成简历'}</button><p className="wb-hint">{blocked || (markdown ? '重新生成将替换当前稿件，包括手动修改；如需保留请先下载。' : '只改写与排序，不新增经历事实。')}</p>
        {markdown && (blocked ? <p className="warning-note" role="status">以下是保留的草稿，尚不能作为当前已确认结果。请补全真实事实、重新确认后生成。</p> : <p className={review.warning || tailoringNeedsReview ? 'warning-note' : 'wb-success'} role="status">简历已生成草稿，可预览和编辑；请核对下方检查信息后再下载使用。</p>)}
        {markdown && <div className="wb-review warning-note" role="status" aria-label="生成稿检查状态"><strong>{review.title}</strong><p>{review.detail}</p><p>请逐句核对职责、动作、上线/落地、成果和数字。原材料未说明的内容不能因 AI 润色就当成事实；自动检查及数字检查通过也不等于事实认证。</p></div>}
        {markdown && jdText.trim() && !initialDraft && <section className="wb-tailoring" aria-label="岗位定制依据"><h3>这份简历如何针对岗位调整</h3>{tailoring ? <>
          <p>本次规划经历顺序：{tailoring.selected_experiences.map((item) => item.name).join(' → ')}</p>
          <p className="wb-hint">已逐条核对 JD 原文条目（含标题和背景）。{tailoring.revision_count === 1 ? '已自动定向修订 1 次并重新复核；仍有警告的内容请人工修改，不代表已通过。' : '未触发自动定向修订。'}</p>
          <p className="wb-hint">{tailoring.review_note}“有相关依据”可能只是部分支持，不等于满足整条要求。</p>
          {tailoring.requirements.map((item) => <details key={item.id} open={item.priority === 'core'}><summary>{item.priority === 'core' ? '核心' : '补充'} · {item.requirement} — {item.status === 'gap' ? '缺少事实依据' : item.status === 'omitted' ? '相关经历未选入' : item.output_excerpt ? '有相关依据与正文摘录' : '有依据但正文未体现'}</summary>
            {item.evidence.length ? <ul>{item.evidence.map((fact) => <li key={fact.id}>{fact.experience_name}：{fact.text}</li>)}</ul> : <p>现有已确认事实不能支撑；仅在你确实做过时补充材料，不会自动补写能力。</p>}
            {item.output_excerpt && <p>本稿摘录：<q>{item.output_excerpt}</q></p>}
            {item.status === 'supported' && !item.output_excerpt && <p className="warning-note">模型复核未找到对应表达，请核对或重新生成，不能仅视作定制完成。</p>}
            {item.status === 'omitted' && <p>受经历数量限制，本次没有选入对应经历；可精简无关经历后重新确认生成。</p>}
          </details>)}
          {tailoring.unsupported_claims.length > 0 && <div className="warning-note" role="status"><strong>以下表述可能超出事实，请勿直接使用</strong><ul>{tailoring.unsupported_claims.map((claim, i) => <li key={i}><q>{claim.quote}</q>：{claim.reason}</li>)}</ul></div>}
        </> : <p className="warning-note">定制依据待核对：未收到与当前材料、JD 和稿件对应的完整报告。编辑或恢复的草稿不沿用旧报告，请重新生成或人工逐项核对。</p>}</section>}
        {markdown ? <><div className="preview-toolbar"><div className="segmented"><button className={previewMode === 'preview' ? 'selected' : ''} disabled={busy} onClick={() => setPreviewMode('preview')}>预览</button><button className={previewMode === 'edit' ? 'selected' : ''} disabled={busy} onClick={() => setPreviewMode('edit')}>编辑</button></div><span className="muted">Markdown</span></div>{previewMode === 'preview' ? <ResumePreview markdown={markdown} /> : <textarea className="markdown-editor" aria-label="编辑简历 Markdown" disabled={busy} value={markdown} onChange={(e) => editMarkdown(e.target.value)} />}
          {manuallyEdited && <p className="warning-note">稿件已手动修改，原数字检查不再代表当前内容，请重新核对所有事实和数字。</p>}
          {numberWarnings.length > 0 && <div className="warning-note" role="status"><strong>数字检查：以下内容缺少材料依据</strong><ul>{numberWarnings.map((item, i) => <li key={i}>{item}</li>)}</ul></div>}<p className="field-hint">初稿及手动修改均需人工核对，数字检查不等于事实认证。</p><button className="secondary-button full" disabled={busy || !markdown.trim()} onClick={download}><UiIcon name="download" />下载 Markdown 简历</button></> : <div className="preview-empty"><div className="paper-skeleton"><span className="skeleton-name" /><span className="skeleton-sub" /><div className="skeleton-divider" /><span className="skeleton-title" /><span /><span /><span className="short" /><div className="skeleton-divider" /><span className="skeleton-title" /><span /><span className="short" /></div><h3>你的下一份简历，从这里开始</h3><p>确认经历并生成初稿后，结果会显示在这里。</p></div>}
        <div className="export-note">本轮支持 Markdown；Word 和 PDF 可在个人记忆页导出。</div>{stepActions(4)}
        <div className="step-actions"><button type="button" className="secondary-button" disabled={busy} onClick={() => setActiveStep(3)}>返回检查与优化</button><button type="button" className="primary-button" disabled={busy || !jdText.trim() || !markdown.trim() || Boolean(blocked)} onClick={onInterview}>准备模拟面试</button></div>{!jdText.trim() && <p className="wb-hint">准备面试前请返回检查与优化填写目标岗位要求，当前简历会保留。</p>}
      </section>
    </div>
  </div>
}
