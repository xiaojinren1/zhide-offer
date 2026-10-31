import { useEffect, useRef, useState } from 'react'
import type { ResumeProfile } from '../lib/types'
import type { InterviewRecord } from '../lib/workspace'
import { ACCOUNT_CHANGED_EVENT, api, apiErrorMessage } from '../lib/api'
import { interviewClient } from './interview/client'
import { BankView } from './interview/BankView'
import { ReportView } from './interview/ReportView'
import { answerError, formatTime, MAX_ANSWER_LENGTH, PracticeClock } from './interview/practice'
import { createRequestId } from './interview/requestId'
import { isBank, isContext, isReport, isSnapshot, isTurn, object } from './interview/types'
import type { Bank, Session, ReportResponse, Turn } from './interview/types'
import './interview/interview.css'

interface Props { userId?: string; jdText: string; profile: ResumeProfile | null; markdown: string }
type HistoryItem = Pick<InterviewRecord, 'id' | 'title' | 'saved_at'>
const stageNames: Record<string, string> = { introduction: '自我介绍', deep_dive: '经历与专业深挖', scenario: '岗位情景', candidate_questions: '候选人反问' }

export default function InterviewPage({ userId: suppliedUserId, jdText, profile, markdown }: Props) {
  const [userId, setUserId] = useState(suppliedUserId || '')
  const [bank, setBank] = useState<Bank | null>(null)
  const [session, setSession] = useState<Session | null>(null)
  const [result, setResult] = useState<ReportResponse | null>(null)
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [tab, setTab] = useState<'bank' | 'history' | 'report'>('bank')
  const [history, setHistory] = useState<HistoryItem[]>([])
  const [legacy, setLegacy] = useState<InterviewRecord | null>(null)
  const [elapsed, setElapsed] = useState(0)
  const [ending, setEnding] = useState(false)
  const [highlight, setHighlight] = useState('')
  const [deleteId, setDeleteId] = useState('')
  const [prestart, setPrestart] = useState<'direct' | 'bank' | null>(null)
  const controller = useRef(new AbortController())
  const alive = useRef(true)
  const working = useRef(false)
  const clock = useRef(new PracticeClock())
  const pending = useRef<{ key: string; body: Record<string, unknown> } | null>(null)
  const finishBody = useRef<Record<string, unknown> | null>(null)
  const materials = JSON.stringify({ profile, markdown, jdText })
  const bankMaterials = useRef('')
  const ready = Boolean(userId && profile?.user_confirmed && profile.experiences.length && markdown.trim() && jdText.trim())
  const stale = Boolean(bank && bankMaterials.current !== materials)
  const active = Boolean(session && !result)
  const unsaved = Boolean(result && !result.saved)
  const missing = [!userId && '登录账户', (!profile?.user_confirmed || !profile.experiences.length) && '已确认的经历',
    !markdown.trim() && '最新生成的简历', !jdText.trim() && '岗位 JD'].filter(Boolean)
  const preview = prestart === 'bank' && bank ? bank.snapshot : { resume_markdown: markdown, jd_text: jdText, captured_at: '当前工作台最新生成版本' }

  useEffect(() => {
    alive.current = true
    controller.current = new AbortController()
    const current = controller.current
    const clear = () => {
      alive.current = false; current.abort(); clock.current.pause()
      setUserId(''); setBank(null); setSession(null); setResult(null); setDraft(''); setHistory([]); setLegacy(null)
      setError('账户已变化，请重新进入面试页面。')
    }
    window.addEventListener(ACCOUNT_CHANGED_EVENT, clear)
    if (suppliedUserId) setUserId(suppliedUserId)
    else void api.me().then((r) => { if (!current.signal.aborted) setUserId(r.user.id) }).catch((e) => { if (!current.signal.aborted) setError(apiErrorMessage(e)) })
    void api.listInterviewRecords().then((r) => { if (!current.signal.aborted) setHistory(r.records) }).catch((e) => { if (!current.signal.aborted) setError(apiErrorMessage(e)) })
    return () => { alive.current = false; current.abort(); clock.current.pause(); window.removeEventListener(ACCOUNT_CHANGED_EVENT, clear) }
  }, [])

  useEffect(() => {
    if (!active || ending || busy) { clock.current.pause(); return }
    clock.current.resume()
    const timer = window.setInterval(() => setElapsed(clock.current.seconds()), 500)
    return () => { clearInterval(timer); clock.current.pause() }
  }, [active, ending, busy])

  useEffect(() => {
    if (!active && !unsaved) return
    const warn = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = '' }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [active, unsaved])

  async function run(action: () => Promise<void>) {
    if (working.current || !alive.current) return
    working.current = true; clock.current.pause(); setElapsed(clock.current.seconds()); setBusy(true); setError('')
    try { await action() } catch (e) { if (alive.current) setError(apiErrorMessage(e)) }
    finally { working.current = false; if (alive.current) setBusy(false) }
  }
  function requestBody(key: string, body: Record<string, unknown>) {
    if (pending.current?.key !== key) pending.current = { key, body: { ...body, expected_user_id: userId, request_id: createRequestId() } }
    return pending.current!.body
  }
  async function refreshHistory() {
    const data = await api.listInterviewRecords()
    if (alive.current) setHistory(data.records)
  }
  function generate() {
    if (!ready || unsaved) return
    void run(async () => {
      const body = requestBody('bank:' + materials, { resume_profile: profile, resume_markdown: markdown, jd_text: jdText })
      const value = await interviewClient.bank(body, controller.current.signal)
      if (!alive.current) return
      setBank(value); bankMaterials.current = materials; setSession(null); setResult(null); setLegacy(null); setEnding(false)
      setTab('bank'); setPrestart(null); setHighlight(''); pending.current = null; finishBody.current = null
    })
  }
  function start() {
    if (!prestart || !ready || unsaved || (prestart === 'bank' && (!bank || stale))) return
    void run(async () => {
      const mode = prestart
      const key = mode === 'bank' ? 'start:bank:' + bank!.id : 'start:direct:' + materials
      const body = mode === 'bank' ? { bank_id: bank!.id } : { resume_profile: profile, resume_markdown: markdown, jd_text: jdText }
      const value = await interviewClient.start(requestBody(key, body), controller.current.signal)
      if (!alive.current) return
      if (mode === 'direct') setBank(null)
      setSession(value); setResult(null); setEnding(false); setDraft(''); setElapsed(0); clock.current = new PracticeClock()
      setLegacy(null); setPrestart(null); pending.current = null; finishBody.current = null
    })
  }
  function submit(skip = false) {
    if (!session || ending) return
    if (!skip) { const message = answerError(draft); if (message) { setError(message); return } }
    void run(async () => {
      const key = `turn:${session.id}:${session.version}:${skip}:${draft}`
      const value = await interviewClient.turn(requestBody(key, { session_id: session.id, version: session.version,
        answer: skip ? '' : draft, skip, elapsed_seconds: clock.current.seconds() }), controller.current.signal)
      if (!alive.current) return
      setSession(value); setDraft(''); pending.current = null
    })
  }
  function finish() {
    if (!session) return
    if (draft.length > MAX_ANSWER_LENGTH) { setError(answerError(draft) || '回答过长'); return }
    void run(async () => {
      if (!finishBody.current) finishBody.current = {
        expected_user_id: userId, request_id: createRequestId(), session_id: session.id, version: session.version,
        elapsed_seconds: clock.current.seconds(), final_answer: draft,
      }
      setEnding(true)
      const value = await interviewClient.report(finishBody.current, controller.current.signal)
      if (!alive.current) return
      setSession(value.session); setResult(value); setDraft(''); setTab('report'); pending.current = null
      if (value.saved) await refreshHistory()
    })
  }
  function loadHistory(id: string) {
    if (unsaved) { setError('请先保存当前报告，再载入其他记录。'); return }
    void run(async () => {
      const { record } = await api.loadInterviewRecord(id)
      if (!alive.current) return
      const feedback = record.overall_feedback
      if (object(feedback) && [2, 3].includes(Number(feedback.schema_version))) {
        if (!isReport(feedback.report) || !isSnapshot(feedback.snapshot) || !Array.isArray(feedback.transcript) || !feedback.transcript.every(isTurn)
          || typeof feedback.elapsed_seconds !== 'number') throw new Error('历史记录格式不完整，请重新加载。')
        const direct = feedback.schema_version === 3 && feedback.mode === 'direct'
        if (feedback.schema_version === 3 && (!isContext(feedback.context) || !['bank', 'direct'].includes(String(feedback.mode))
          || (direct && feedback.bank !== null))) throw new Error('历史主题格式不完整，请重新加载。')
        const restoredBank = object(feedback.bank) ? { ...feedback.bank, snapshot: feedback.snapshot, id: 'history-' + record.id } : null
        if (!direct && !isBank(restoredBank, true)) throw new Error('历史题库格式不完整，请重新加载。')
        const historicalBank = isBank(restoredBank, true) ? restoredBank : null
        const restored: Session = { id: record.id, bank_id: historicalBank?.id || null, mode: direct ? 'direct' : 'bank',
          snapshot: feedback.snapshot, version: 1, status: 'ended', turns: feedback.transcript as Turn[],
          elapsed_seconds: feedback.elapsed_seconds, job_title: historicalBank?.job_title || (isContext(feedback.context) ? feedback.context.job_title : ''), started_at: record.saved_at }
        bankMaterials.current = '' // 历史题库仅回看，下一轮必须按当前材料重新生成。
        setBank(historicalBank); setSession(restored); setResult({ ok: true, session: restored, report: feedback.report, saved: true, save_error: null, record_id: record.id })
        setTab('report'); setLegacy(null); setEnding(false); setPrestart(null); finishBody.current = null
      } else { setLegacy(record); setTab('history') }
    })
  }
  function removeHistory(id: string) {
    void run(async () => { await api.deleteInterviewRecord(id); if (!alive.current) return; setHistory((list) => list.filter((r) => r.id !== id)); setDeleteId(''); if (legacy?.id === id) setLegacy(null) })
  }
  function prepareAgain() {
    setSession(null); setResult(null); setEnding(false); setDraft(''); setTab('bank'); setElapsed(0); setPrestart(null)
    clock.current = new PracticeClock(); finishBody.current = null; pending.current = null
  }

  return <div className="interview-page space-y-5">
    <header className="page-heading" style={{ marginBottom: 0 }}><div><span className="eyebrow">PERSONAL INTERVIEW LAB</span><h1>{active ? '连续模拟面试' : '个性化面试准备'}</h1><p>{active ? '按真实经历作答，结束后统一复盘。' : '先用题库准备，或直接开始一场完整面试。'}</p></div><span className="heading-badge">文字面试 · 建议 15 分钟</span></header>
    {error && <div className="error-banner" role="alert">{error}</div>}
    {!active && <nav className="interview-tabs" aria-label="面试视图"><button className="secondary-button" aria-pressed={tab === 'bank'} disabled={busy} onClick={() => setTab('bank')}>个性化题库</button><button className="secondary-button" disabled={busy || unsaved} onClick={() => { setTab('bank'); setPrestart('direct') }}>全真模拟面试</button><button className="secondary-button" aria-pressed={tab === 'history'} disabled={busy} onClick={() => { setTab('history'); void run(refreshHistory) }}>面试历史</button>{result && <button className="secondary-button" disabled={busy} onClick={() => setTab('report')}>本轮报告</button>}</nav>}

    {!active && tab === 'bank' && <>
      <div className="interview-entry-grid"><section className="panel"><span className="section-kicker">PREPARE WITH EVIDENCE</span><h2>生成个性化题库</h2>
        <p>根据相关经历和岗位重点生成 10–30 道题，覆盖经历深挖、专业能力、行为情景与动机。每题附出题依据、追问和折叠示范回答。</p>
        <div className="interview-actions"><button className="primary-button" disabled={busy || !ready || unsaved} onClick={generate}>{busy ? '处理中…' : bank ? '按当前材料重新生成题库' : '生成个性化题库'}</button></div>
      </section><section className="panel"><span className="section-kicker">REALISTIC INTERVIEW</span><h2>直接进入全真模拟</h2><p>无需先生成或看完题库。面试官根据最新简历与 JD 动态追问，结束后统一评价。</p><div className="interview-actions"><button className="primary-button" disabled={busy || !ready || unsaved} onClick={() => setPrestart('direct')}>直接进入全真模拟</button></div></section></div>
      {!ready && <div className="notice">尚缺：{missing.join('、')}。请在工作台补齐后开始，两个入口会保留。</div>}
      {stale && <div className="notice">题库材料与当前工作台不同，仅供回看。可重新生成题库，或按最新材料直接模拟。</div>}
      {bank && <section className="panel"><h2>{bank.job_title} · {bank.questions.length} 道个性化题</h2><p>不必先看完题库；模拟将沿用这些能力主题，变换问法并动态追问。</p><button className="primary-button" disabled={busy || stale || !ready || unsaved} onClick={() => setPrestart('bank')}>从这份题库进入模拟</button></section>}
      {prestart && <section className="panel"><span className="section-kicker">BEFORE YOU BEGIN</span><h2>确认本轮模拟材料与规则</h2><p>入口：{prestart === 'direct' ? '直接模拟' : '题库模拟'} · 目标岗位：{prestart === 'bank' && bank ? bank.job_title : jdText.split('\n').find((line) => line.trim()) || '尚未填写'}</p><p>简历版本：{preview.captured_at}</p>
        <details><summary>核对本轮简历与 JD</summary><pre>{preview.resume_markdown}</pre><pre>{preview.jd_text}</pre></details>
        <p>开始后冻结本轮材料。按自我介绍、经历与专业深挖、岗位情景、候选人反问推进；不要求问满 10 题。</p>
        <p>开始后隐藏题库与示范回答；可以跳过或回答不知道，结束后统一评价。等待模型不计时，15 分钟只提醒收尾，可继续或主动结束。</p>
        <p className="muted">本版仅保存已结束面试，刷新或离开页面后无法续接进行中的对话。</p>
        <button className="primary-button" disabled={busy || (prestart === 'bank' && stale) || !ready || unsaved} onClick={start}>{busy ? '正在准备首问…' : '开始连续模拟面试'}</button>
      </section>}
      {bank && <BankView bank={bank} highlighted={highlight} />}
    </>}

    {active && session && <div className="interview-chat space-y-4">
      <div className="activity-banner"><strong>{session.job_title} · {stageNames[session.turns.at(-1)!.question.stage] || '面试进行中'}</strong><span className="interview-clock">累计用时 {formatTime(elapsed)}{busy ? ' · 等待期间暂停计时' : ''}</span></div>
      {elapsed >= 900 && <div className="notice" role="status">已练习 15 分钟，建议准备收尾。你可以继续回答，也可以主动结束。</div>}
      {session.turns.map((t, i) => <article className="panel interview-question" key={t.id}><span className="section-kicker">面试官 · {i + 1}{t.question.is_follow_up ? ' · 追问' : ''}</span><h2>{t.question.text}</h2>{t.answer !== null && <div className="interview-answer">{t.skipped ? '【跳过】' : t.answer}</div>}</article>)}
      {ending ? <section className="panel"><h2>本轮已进入结束复盘</h2><p>已有回答会保留。报告失败时可以重试，不会编造评分或重复提交最后一条回答。</p><button className="primary-button" disabled={busy} onClick={finish}>{busy ? '生成报告中…' : '重试生成报告'}</button></section> : <section className="panel"><label className="field-label" htmlFor="interview-answer">你的回答 <span>{draft.length} / {MAX_ANSWER_LENGTH} 字</span></label><textarea id="interview-answer" value={draft} maxLength={MAX_ANSWER_LENGTH} rows={6} disabled={busy} onChange={(e) => setDraft(e.target.value)} placeholder="输入你的真实回答…" />
        <div className="interview-actions"><button className="primary-button" disabled={busy} onClick={() => submit()}>{busy ? '面试官思考中…' : '提交回答'}</button><button className="secondary-button" disabled={busy || Boolean(draft.trim())} onClick={() => submit(true)}>跳过这道题</button><button className="secondary-button" disabled={busy} onClick={finish}>{draft.trim() ? '提交当前回答并结束' : '结束并生成整体报告'}</button></div>
        {session.turns.at(-1)!.question.suggest_finish && <p className="muted">主要主题已覆盖，可以准备结束；也可以继续交流。</p>}
      </section>}
    </div>}

    {!active && tab === 'report' && result && <>
      <div className={result.saved ? 'notice' : 'error-banner'} role="status">{result.saved ? '本轮已保存，可在面试历史查看。' : result.save_error}{!result.saved && <button className="secondary-button" disabled={busy} onClick={finish}>重试保存</button>}</div>
      <ReportView report={result.report} turns={result.session.turns} elapsed={result.session.elapsed_seconds} bank={bank} snapshot={result.session.snapshot || bank?.snapshot || null} onTopic={(id) => { setHighlight(id); setTab('bank'); setTimeout(() => document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' }), 0) }} />
      <button className="primary-button" disabled={busy || !result.saved} onClick={prepareAgain}>返回准备页，开始下一轮</button>
    </>}

    {!active && tab === 'history' && <section className="panel"><h2>已结束的面试</h2>{history.length === 0 && <p className="muted">还没有保存的面试记录。</p>}{history.map((r) => <article key={r.id}><h3>{r.title}</h3><p className="muted">{r.saved_at}</p><div className="interview-actions"><button className="secondary-button" disabled={busy} onClick={() => loadHistory(r.id)}>查看报告与对话</button>{deleteId === r.id ? <><span>确定删除这条记录？</span><button className="secondary-button" disabled={busy} onClick={() => removeHistory(r.id)}>确认删除</button><button className="secondary-button" onClick={() => setDeleteId('')}>取消</button></> : <button className="memory-danger" disabled={busy} onClick={() => setDeleteId(r.id)}>删除</button>}</div></article>)}
      {legacy && <details open><summary>旧版三题记录：{legacy.title}</summary><p className="muted">旧版规则评分记录，仅供回看，不作为新版整体评价。</p><pre>{JSON.stringify(legacy, null, 2)}</pre></details>}
    </section>}
  </div>
}
