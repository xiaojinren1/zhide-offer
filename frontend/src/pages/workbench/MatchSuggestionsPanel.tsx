import { useEffect, useRef, useState } from 'react'
import { api } from '../../lib/api'
import type { MatchReport, ResumeProfile } from '../../lib/types'
import { operationError } from './state'
import { chosenMatchSuggestions, matchInputSnapshot, matchSuggestions } from './matchSuggestions'

interface Props {
  report: MatchReport | null
  reportInput: string
  jdText: string
  profile: ResumeProfile | null
  markdown: string
  onMarkdownChange: (markdown: string) => void
  onApplied: (message: string) => void
  onBusyChange?: (busy: boolean) => void
  disabled?: boolean
}

// Place alongside the diagnosis report. The page owns report invalidation and the success message.
export default function MatchSuggestionsPanel({ report, reportInput, jdText, profile, markdown,
  onMarkdownChange, onApplied, onBusyChange, disabled = false }: Props) {
  const snapshot = matchInputSnapshot(jdText, profile, markdown)
  const observed = useRef({ report, reportInput, snapshot, version: 0, valid: reportInput === snapshot })
  const current = observed.current
  if (current.report !== report || current.reportInput !== reportInput) {
    observed.current = { report, reportInput, snapshot, version: current.version + 1, valid: reportInput === snapshot }
  } else if (current.snapshot !== snapshot) {
    observed.current = { ...current, snapshot, version: current.version + 1, valid: false }
  }
  const version = observed.current.version
  const [selection, setSelection] = useState<{ version: number; ids: string[] }>({ version, ids: [] })
  const [error, setError] = useState<{ version: number; message: string } | null>(null)
  const [applying, setApplying] = useState(false)
  const [consumed, setConsumed] = useState<MatchReport | null>(null)
  const locked = useRef(false)
  const mounted = useRef(true)
  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false }
  }, [])
  const visible = report && observed.current.valid && consumed !== report
  const suggestions = visible ? matchSuggestions(report) : []
  const selected = selection.version === version ? selection.ids : []
  const canApply = Boolean(visible && profile?.user_confirmed === true && markdown.trim())
  const unavailable = disabled || applying || !canApply

  const apply = async () => {
    if (locked.current || unavailable || !report || !profile) return
    let chosen: ReturnType<typeof chosenMatchSuggestions>
    try { chosen = chosenMatchSuggestions(report, selected) }
    catch (reason) { setError({ version, message: operationError(reason) }); return }
    locked.current = true
    setApplying(true); setError(null); onBusyChange?.(true)
    try {
      const result = await api.reviseResume(jdText, profile, markdown, chosen)
      if (!mounted.current || observed.current.version !== version || !observed.current.valid) return
      if (result.ok !== true || typeof result.markdown !== 'string' || !result.markdown.trim()) {
        throw new Error(result.error || '未生成新的简历，请重试。')
      }
      if (result.untraceable !== undefined && (!Array.isArray(result.untraceable) || result.untraceable.some(x => typeof x !== 'string'))) {
        throw new Error('简历校验结果格式无效，请重试。')
      }
      const warning = result.untraceable?.length
        ? ` 检测到缺少材料依据的数字：${result.untraceable.join('、')}，请核对并删除或补充真实依据。` : ''
      setConsumed(report); setSelection({ version, ids: [] })
      onMarkdownChange(result.markdown)
      onApplied(`已按 ${chosen.length} 条岗位匹配建议更新简历。请重新诊断、运行质检并人工核对。${warning}`)
    } catch (reason) {
      if (mounted.current && observed.current.version === version && observed.current.valid) {
        setError({ version, message: operationError(reason) })
      }
    } finally {
      locked.current = false
      if (mounted.current) { setApplying(false); onBusyChange?.(false) }
    }
  }

  if (!visible) return null
  return <section className="match-suggestions-panel space-y-3 rounded-xl border border-teal-200 bg-teal-50 p-4" aria-label="采纳岗位匹配建议" aria-busy={applying}>
    <h3 className="text-sm font-medium">按岗位匹配结果优化当前简历</h3>
    <p className="wb-hint">只调整已确认经历的表达与顺序。缺少事实依据的要求不能采纳，请先补充真实材料。</p>
    {!canApply && <p className="wb-hint">请先确认经历并生成简历，再采纳匹配建议。</p>}
    <div className="flex flex-wrap gap-2">
      <button type="button" className="secondary-button" disabled={unavailable || !suggestions.length}
        onClick={() => { if (!unavailable) setSelection({ version, ids: suggestions.map(item => item.id) }) }}>全选有依据的建议</button>
      <button type="button" className="secondary-button" disabled={unavailable || !selected.length}
        onClick={() => { if (!unavailable) setSelection({ version, ids: [] }) }}>清空选择</button>
    </div>
    {suggestions.map(item => <label key={item.id} className="flex items-start gap-2 rounded-lg border border-teal-200 bg-white p-3">
      <input type="checkbox" className="mt-1 shrink-0" disabled={unavailable} checked={selected.includes(item.id)}
        onChange={() => { if (!unavailable) setSelection({ version, ids: selected.includes(item.id) ? selected.filter(id => id !== item.id) : [...selected, item.id] }) }} />
      <span className="min-w-0 break-words text-sm">{item.location}</span>
    </label>)}
    {!suggestions.length && <p className="wb-hint">当前没有可直接采纳的有依据建议。请补充真实经历后重新诊断。</p>}
    <button type="button" className="primary-button" disabled={unavailable || !selected.length} onClick={() => void apply()}>
      {applying ? '正在按匹配建议更新简历…' : `将选中建议更新到简历（${selected.length}）`}
    </button>
    {error?.version === version && <div className="error-banner" role="alert">{error.message}</div>}
  </section>
}
