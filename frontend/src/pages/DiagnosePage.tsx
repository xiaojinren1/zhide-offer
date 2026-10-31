import { useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'
import type { ResumeProfile } from '../lib/types'
import { operationError } from './workbench/state'
import { validateDiagnosis, type ValidatedDiagnosis } from './workbench/diagnose'
import RoleRequirementsEditor from './workbench/RoleRequirementsEditor'
import MatchSuggestionsPanel from './workbench/MatchSuggestionsPanel'
import { matchInputSnapshot } from './workbench/matchSuggestions'
import './workbench/workbench.css'

interface Props {
  jdText: string
  setJdText: (s: string) => void
  profile: ResumeProfile | null
  markdown: string
  onMarkdownChange: (markdown: string) => void
  busy?: boolean
  onBusyChange?: (busy: boolean) => void
  onDone: (jdText: string, keywords: string[]) => void
  onEditResume?: () => void
  onNext?: () => void
  embedded?: boolean
}

const STATUS_STYLE: Record<string, string> = {
  covered: 'bg-green-100 text-green-800',
  partial: 'bg-amber-100 text-amber-800',
  missing: 'bg-red-100 text-red-800',
}
const STATUS_LABEL: Record<string, string> = {
  covered: '已覆盖', partial: '部分覆盖', missing: '缺失',
}

export default function DiagnosePage({ jdText, setJdText, profile, markdown, onMarkdownChange, busy: externalBusy = false, onBusyChange, onDone, onEditResume, onNext, embedded = false }: Props) {
  const [activity, setActivity] = useState<'diagnose' | 'role' | 'apply' | ''>('')
  const [error, setError] = useState('')
  const [errorVersion, setErrorVersion] = useState(0)
  const [applied, setApplied] = useState<{ input: string; message: string } | null>(null)
  const [report, setReport] = useState<ValidatedDiagnosis | null>(null)
  const [reportInput, setReportInput] = useState('')
  const [reportVersion, setReportVersion] = useState(-1)
  const snapshot = matchInputSnapshot(jdText, profile, markdown)
  const latestInput = useRef({ snapshot, version: 0 })
  if (latestInput.current.snapshot !== snapshot) latestInput.current = { snapshot, version: latestInput.current.version + 1 }
  const version = latestInput.current.version
  const requestLock = useRef(false)
  const appliedInput = useRef('')
  const mounted = useRef(true)
  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false }
  }, [])
  const visibleReport = reportInput === snapshot && reportVersion === version ? report : null
  const busy = externalBusy || Boolean(activity)
  const visibleError = errorVersion === version ? error : ''
  const changeBusy = (mode: 'role' | 'apply', value: boolean) => {
    requestLock.current = value
    setActivity(value ? mode : ''); onBusyChange?.(value)
  }
  const editJd = (value: string) => {
    setJdText(value); setReport(null); setError(''); setApplied(null)
  }

  const run = async () => {
    if (!profile || !jdText.trim() || busy || requestLock.current) return
    const input = snapshot
    requestLock.current = true
    setActivity('diagnose'); onBusyChange?.(true); setError(''); setReport(null); setApplied(null)
    try {
      const r = await api.diagnose(jdText, profile)
      if (!mounted.current || latestInput.current.snapshot !== input || latestInput.current.version !== version) return
      const validated = validateDiagnosis(r)
      setReport(validated); setReportInput(input); setReportVersion(version); onDone(jdText, validated.keywords)
    } catch (e) { if (mounted.current && latestInput.current.snapshot === input && latestInput.current.version === version) { setError(operationError(e)); setErrorVersion(version) } }
    finally { requestLock.current = false; if (mounted.current) { setActivity(''); onBusyChange?.(false) } }
  }

  return (
    <div className="role-b-diagnose space-y-5" aria-busy={busy}>
      <header>
        <h2 className="text-lg font-medium">岗位匹配诊断</h2>
        <p className="text-sm text-gray-500 mt-1">依据当前材料对照岗位要求，找出已有证据与待补充项；结果仅供准备参考，不代表招聘结论。</p>
      </header>

      {!embedded && <RoleRequirementsEditor id="diagnose-jd" jdText={jdText} onChange={editJd} disabled={busy} onBusyChange={value => changeBusy('role', value)} />}

      <button onClick={run} disabled={busy || !profile || !jdText.trim()}
        className="px-5 py-2 bg-teal-600 text-white rounded-lg disabled:bg-gray-300">
        {activity === 'diagnose' ? '分析中，请稍候…' : visibleError ? '重试诊断' : visibleReport ? '重新诊断' : '开始诊断'}
      </button>
      {!profile && <p className="wb-hint">请先在简历工作台整理材料，再进行岗位匹配。</p>}
      <p className="wb-hint">修改岗位要求会保留当前简历和事实确认；旧匹配结果失效，请重新诊断。</p>
      {visibleError && <div className="error-banner" role="alert">{visibleError}</div>}
      {applied?.input === snapshot && <p className="warning-note" role="status">{applied.message}</p>}
      {!embedded && <div className="step-actions" aria-label="岗位匹配工具导航">
        <button type="button" className="secondary-button" disabled={busy} onClick={onEditResume}>返回修改简历</button>
        <button type="button" className="primary-button" disabled={busy || !markdown.trim()} onClick={onNext}>继续检查简历</button>
      </div>}

      {visibleReport?.ok && (
        <div className="space-y-4">
          <div className="flex items-center gap-6 bg-white border border-gray-200 rounded-xl p-4">
            <div>
              <div className="text-3xl font-medium text-teal-700">{Math.round(visibleReport.coverage * 100)}%</div>
              <div className="text-xs text-gray-500 mt-0.5">匹配覆盖率</div>
            </div>
            <div className="text-sm text-gray-600">
              岗位：{visibleReport.job_title || '未识别'}
              {visibleReport.missing_hard_count ? ` · 硬性缺失 ${visibleReport.missing_hard_count} 项` : ''}
            </div>
          </div>

          {visibleReport.missing_hard.length > 0 && (
            <div className="bg-red-50 border border-red-200 rounded-xl p-4">
              <h3 className="text-sm font-medium text-red-800">当前材料缺少证据的硬性要求</h3>
              <ul className="mt-2 space-y-1 text-sm text-red-700 list-disc pl-5">
                {visibleReport.missing_hard.map((r, i) => <li key={i}>{r}</li>)}
              </ul>
            </div>
          )}

          <div className="bg-white border border-gray-200 rounded-xl divide-y divide-gray-100">
            {visibleReport.items.map((it, i) => (
              <div key={i} className="p-3 flex items-start gap-3">
                <span className={`text-xs px-2 py-0.5 rounded shrink-0 ${STATUS_STYLE[it.status] || ''}`}>
                  {STATUS_LABEL[it.status] || it.status}
                </span>
                <div className="text-sm">
                  <div>{it.requirement}</div>
                  {it.evidence && <div className="text-gray-500 text-xs mt-0.5">证据：{it.evidence}</div>}
                  {it.note && <div className="text-amber-700 text-xs mt-0.5">{it.note}</div>}
                </div>
              </div>
            ))}
          </div>
          <MatchSuggestionsPanel report={visibleReport} reportInput={reportInput} jdText={jdText} profile={profile} markdown={markdown}
            disabled={busy} onBusyChange={value => changeBusy('apply', value)}
            onMarkdownChange={value => { appliedInput.current = matchInputSnapshot(jdText, profile, value); onMarkdownChange(value) }}
            onApplied={message => { setReport(null); setReportInput(''); setApplied({ input: appliedInput.current, message }) }} />
        </div>
      )}
    </div>
  )
}
