import { useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'
import type { ResumeProfile } from '../lib/types'
import { operationError } from './workbench/state'
import { validateDiagnosis, type ValidatedDiagnosis } from './workbench/diagnose'
import './workbench/workbench.css'

interface Props {
  jdText: string
  setJdText: (s: string) => void
  profile: ResumeProfile | null
  onDone: (jdText: string, keywords: string[]) => void
  onEditResume?: () => void
  onNext?: () => void
}

const STATUS_STYLE: Record<string, string> = {
  covered: 'bg-green-100 text-green-800',
  partial: 'bg-amber-100 text-amber-800',
  missing: 'bg-red-100 text-red-800',
}
const STATUS_LABEL: Record<string, string> = {
  covered: '已覆盖', partial: '部分覆盖', missing: '缺失',
}

export default function DiagnosePage({ jdText, setJdText, profile, onDone, onEditResume, onNext }: Props) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [report, setReport] = useState<ValidatedDiagnosis | null>(null)
  const [reportInput, setReportInput] = useState('')
  const snapshot = JSON.stringify([jdText, profile])
  const latestInput = useRef(snapshot)
  latestInput.current = snapshot
  const requestLock = useRef(false)
  const mounted = useRef(true)
  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false }
  }, [])
  const visibleReport = reportInput === snapshot ? report : null

  const run = async () => {
    if (!profile || !jdText.trim() || requestLock.current) return
    const input = snapshot
    requestLock.current = true
    setBusy(true); setError(''); setReport(null)
    try {
      const r = await api.diagnose(jdText, profile)
      if (!mounted.current || latestInput.current !== input) return
      const validated = validateDiagnosis(r)
      setReport(validated); setReportInput(input); onDone(jdText, validated.keywords)
    } catch (e) { if (mounted.current && latestInput.current === input) setError(operationError(e)) }
    finally { requestLock.current = false; if (mounted.current) setBusy(false) }
  }

  return (
    <div className="role-b-diagnose space-y-5" aria-busy={busy}>
      <header>
        <h2 className="text-lg font-medium">岗位匹配诊断</h2>
        <p className="text-sm text-gray-500 mt-1">依据当前材料对照岗位要求，找出已有证据与待补充项；结果仅供准备参考，不代表招聘结论。</p>
      </header>

      <label className="field-label" htmlFor="diagnose-jd">目标岗位 JD</label>
      <textarea id="diagnose-jd" disabled={busy} value={jdText} onChange={(e) => { setJdText(e.target.value); setReport(null); setError('') }}
        placeholder="粘贴目标岗位的 JD 全文"
        className="w-full h-44 border border-gray-300 rounded-lg p-3 text-sm" />

      <button onClick={run} disabled={busy || !profile || !jdText.trim()}
        className="px-5 py-2 bg-teal-600 text-white rounded-lg disabled:bg-gray-300">
        {busy ? '分析中，请稍候…' : error ? '重试诊断' : visibleReport ? '重新诊断' : '开始诊断'}
      </button>
      {!profile && <p className="wb-hint">请先在简历工作台整理材料，再进行岗位匹配。</p>}
      <p className="wb-hint">修改岗位 JD 会撤销工作台中的事实确认并清空旧简历；生成前请重新确认。匹配结果仅对当前输入有效。</p>
      {error && <div className="error-banner" role="alert">{error}</div>}

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
          <div className="step-actions" aria-label="岗位匹配完成后的操作">
            <button type="button" className="secondary-button" onClick={onEditResume}>根据诊断建议修改简历</button>
            <button type="button" className="primary-button" disabled={!profile || !jdText.trim()} onClick={onNext}>继续检查简历</button>
          </div>
        </div>
      )}
    </div>
  )
}
