import { useState } from 'react'
import { api, apiErrorMessage } from '../lib/api'
import type { QualityReport, ResumeProfile, Suspicion } from '../lib/types'

interface Props {
  jdText: string
  jdKeywords: string[]
  profile: ResumeProfile | null
  markdown: string
  onMarkdownChange: (text: string) => void
}

const SEV: Record<string, string> = {
  high: 'bg-red-100 text-red-800',
  medium: 'bg-amber-100 text-amber-800',
  low: 'bg-gray-100 text-gray-700',
}

function Bar({ label, value }: { label: string; value: number }) {
  const pct = Math.round(value * 100)
  return (
    <div>
      <div className="flex justify-between text-sm mb-1">
        <span>{label}</span><span className="font-medium">{pct}%</span>
      </div>
      <div className="h-2 bg-gray-200 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${pct >= 60 ? 'bg-teal-500' : pct >= 30 ? 'bg-amber-500' : 'bg-red-500'}`}
          style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

export default function QualityPage({ jdText, jdKeywords, profile, markdown, onMarkdownChange }: Props) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [report, setReport] = useState<QualityReport | null>(null)
  const [selected, setSelected] = useState<string[]>([])
  const [applying, setApplying] = useState(false)
  const [applyMessage, setApplyMessage] = useState('')

  const run = async () => {
    if (!profile) return
    setBusy(true); setError('')
    try {
      const r = await api.quality(jdText, profile, markdown, jdKeywords)
      if (r.ok) { setReport(r); setSelected([]); setApplyMessage('') } else { setError(r.error || '质检失败') }
    } catch (e) { setError(apiErrorMessage(e)) } finally { setBusy(false) }
  }

  const suggestions = report ? [
    ...report.suspicions.map((x, index) => ({ ...x, id: `suspicion-${index}` })),
    ...report.cliche_hits.map((x, index) => ({ id: `cliche-${index}`, type: 'cliche', location: '简历正文', detail: `命中套话：${x}`, suggestion: `删除或改写“${x}”，换成真实行动和结果。`, severity: 'medium' as const, program_verified: true })),
    ...report.ats_issues.map((x, index) => ({ id: `ats-${index}`, type: 'ats', location: '简历格式', detail: x, suggestion: '调整简历内容以改善 ATS 解析；缺少联系方式时请先在原始材料中补充真实信息。', severity: 'medium' as const, program_verified: true })),
    ...report.consistency_issues.map((x, index) => ({ id: `consistency-${index}`, type: 'consistency', location: '简历正文', detail: x, suggestion: '删除无法从经历库核实的数字或内容，不要补造事实。', severity: 'high' as const, program_verified: true })),
  ] : []
  const toggleSuggestion = (id: string) => setSelected((previous) => previous.includes(id) ? previous.filter((item) => item !== id) : [...previous, id])
  const applySuggestions = async (all = false) => {
    if (!profile || !markdown.trim() || applying) return
    const chosen = all ? suggestions : suggestions.filter((item) => selected.includes(item.id))
    if (!chosen.length) { setApplyMessage('请先选择至少一条建议。'); return }
    setApplying(true); setError(''); setApplyMessage('')
    try {
      const result = await api.reviseResume(jdText, profile, markdown, chosen)
      if (!result.ok || !result.markdown?.trim()) throw new Error(result.error || '未生成新的简历')
      onMarkdownChange(result.markdown)
      setApplyMessage(`已应用 ${chosen.length} 条建议，请重新运行质检确认结果。`)
      setSelected([])
    } catch (reason) { setError(apiErrorMessage(reason)) } finally { setApplying(false) }
  }

  const s = (x: Suspicion) => (
    <li key={x.detail + x.location} className="border-l-2 border-gray-300 pl-3">
      <div className="flex items-center gap-2">
        <span className={`text-xs px-1.5 py-0.5 rounded ${SEV[x.severity] || ''}`}>{x.severity}</span>
        <span className="text-sm font-medium">{x.type}</span>
        <span className="text-xs text-gray-500">{x.location}</span>
      </div>
      <p className="text-sm text-gray-700 mt-0.5">{x.detail}</p>
      <p className="text-xs text-teal-700 mt-0.5">建议：{x.suggestion}</p>
    </li>
  )

  return (
    <div className="space-y-5">
      <header>
        <h2 className="text-lg font-medium">第四步 · 质检报告</h2>
        <p className="text-sm text-gray-500 mt-1">全部指标由程序判定——AI 生成完，立刻自己给自己打分。</p>
      </header>

      <button onClick={run} disabled={busy || !profile}
        className="px-5 py-2 bg-teal-600 text-white rounded-lg disabled:bg-gray-300">
        {busy ? '质检中…' : '运行质检'}
      </button>
      {error && <p className="text-sm text-red-600">{error}</p>}

      {report && (
        <div className="space-y-4">
          <div className={`rounded-xl p-4 border ${
            report.passed ? 'bg-green-50 border-green-200' : 'bg-amber-50 border-amber-200'
          }`}>
            <span className={`font-medium ${report.passed ? 'text-green-800' : 'text-amber-800'}`}>
              {report.passed ? '质检通过' : '未通过：以下项需处理'}
            </span>
          </div>

          <div className="bg-white border border-gray-200 rounded-xl p-4 space-y-3">
            <Bar label="JD 关键词覆盖率" value={report.keyword_coverage} />
            <Bar label="量化表述密度" value={report.quantified_ratio} />
          </div>

          {suggestions.length > 0 && <div className="bg-blue-50 border border-blue-200 rounded-xl p-4 space-y-3"><div className="flex flex-wrap items-center justify-between gap-2"><div><h3 className="text-sm font-medium text-blue-900">可采纳建议（{suggestions.length}）</h3><p className="text-sm text-blue-800 mt-1">选择后应用到当前简历，也可以一次性全部采纳。</p></div><div className="flex gap-2"><button className="px-3 py-1.5 text-sm border border-blue-300 rounded-lg bg-white" disabled={applying || !markdown.trim()} onClick={() => setSelected(suggestions.map((item) => item.id))}>全选</button><button className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded-lg disabled:bg-gray-300" disabled={applying || !markdown.trim()} onClick={() => void applySuggestions(true)}>{applying ? '应用中…' : '全部采纳并修改简历'}</button></div></div>{suggestions.map((item) => <label key={item.id} className="block bg-white border border-blue-100 rounded-lg p-3 cursor-pointer"><div className="flex gap-2"><input type="checkbox" checked={selected.includes(item.id)} disabled={applying || !markdown.trim()} onChange={() => toggleSuggestion(item.id)} /><div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><span className={`text-xs px-1.5 py-0.5 rounded ${SEV[item.severity] || ''}`}>{item.severity}</span><strong className="text-sm">{item.type}</strong><span className="text-xs text-gray-500">{item.location}</span></div><p className="text-sm text-gray-700 mt-1">{item.detail}</p><p className="text-sm text-teal-700 mt-1">建议：{item.suggestion}</p></div></div></label>)}<button className="w-full px-4 py-2 bg-teal-600 text-white rounded-lg disabled:bg-gray-300" disabled={applying || !markdown.trim() || selected.length === 0} onClick={() => void applySuggestions()}>{applying ? '正在按建议修改简历…' : `采纳选中建议并修改简历（${selected.length}）`}</button>{applyMessage && <p className="text-sm text-teal-700" role="status">{applyMessage}</p>}</div>}
          {report.ats_issues.length > 0 && (
            <div className="bg-white border border-gray-200 rounded-xl p-4">
              <h3 className="text-sm font-medium">ATS 友好度问题</h3>
              <ul className="text-sm text-gray-600 mt-1 list-disc pl-5">
                {report.ats_issues.map((x, i) => <li key={i}>{x}</li>)}
              </ul>
            </div>
          )}
          {report.consistency_issues.length > 0 && (
            <div className="bg-red-50 border border-red-200 rounded-xl p-4">
              <h3 className="text-sm font-medium text-red-800">与经历库不一致（疑似虚构）</h3>
              <ul className="text-sm text-red-700 mt-1 list-disc pl-5">
                {report.consistency_issues.map((x, i) => <li key={i}>{x}</li>)}
              </ul>
            </div>
          )}
          {report.suspicions.length > 0 && (
            <div className="bg-white border border-gray-200 rounded-xl p-4">
              <h3 className="text-sm font-medium">可复核疑点（{report.suspicions.length}）</h3>
              <ul className="mt-2 space-y-2">{report.suspicions.map(s)}</ul>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
