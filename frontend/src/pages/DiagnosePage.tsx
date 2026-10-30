import { useState } from 'react'
import { api } from '../lib/api'
import type { ResumeProfile } from '../lib/types'

interface Props {
  jdText: string
  setJdText: (s: string) => void
  profile: ResumeProfile | null
  onDone: (jdText: string, keywords: string[]) => void
}

const STATUS_STYLE: Record<string, string> = {
  covered: 'bg-green-100 text-green-800',
  partial: 'bg-amber-100 text-amber-800',
  missing: 'bg-red-100 text-red-800',
}
const STATUS_LABEL: Record<string, string> = {
  covered: '已覆盖', partial: '部分覆盖', missing: '缺失',
}

export default function DiagnosePage({ jdText, setJdText, profile, onDone }: Props) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [report, setReport] = useState<Awaited<ReturnType<typeof api.diagnose>> | null>(null)

  const run = async () => {
    if (!profile || !jdText.trim()) return
    setBusy(true); setError('')
    try {
      const r = await api.diagnose(jdText, profile)
      if (r.ok) { setReport(r); onDone(jdText, r.jd?.keywords || []) } else setError(r.error || '诊断失败')
    } catch (e) { setError(String(e)) } finally { setBusy(false) }
  }

  return (
    <div className="space-y-5">
      <header>
        <h2 className="text-lg font-medium">第二步 · JD 匹配诊断</h2>
        <p className="text-sm text-gray-500 mt-1">投前 30 秒知道：这个岗位你会不会被直接刷掉、差在哪。</p>
      </header>

      <textarea value={jdText} onChange={(e) => setJdText(e.target.value)}
        placeholder="粘贴目标岗位的 JD 全文"
        className="w-full h-44 border border-gray-300 rounded-lg p-3 text-sm" />

      <button onClick={run} disabled={busy || !profile || !jdText.trim()}
        className="px-5 py-2 bg-teal-600 text-white rounded-lg disabled:bg-gray-300">
        {busy ? '分析中…' : '开始诊断'}
      </button>
      {error && <p className="text-sm text-red-600">{error}</p>}

      {report?.ok && (
        <div className="space-y-4">
          <div className="flex items-center gap-6 bg-white border border-gray-200 rounded-xl p-4">
            <div>
              <div className="text-3xl font-medium text-teal-700">{Math.round(report.coverage * 100)}%</div>
              <div className="text-xs text-gray-500 mt-0.5">匹配覆盖率</div>
            </div>
            <div className="text-sm text-gray-600">
              岗位：{report.job_title || '未识别'}
              {report.missing_hard_count ? ` · 硬性缺失 ${report.missing_hard_count} 项` : ''}
            </div>
          </div>

          {report.missing_hard.length > 0 && (
            <div className="bg-red-50 border border-red-200 rounded-xl p-4">
              <h3 className="text-sm font-medium text-red-800">会被直接刷掉的风险点</h3>
              <ul className="mt-2 space-y-1 text-sm text-red-700 list-disc pl-5">
                {report.missing_hard.map((r, i) => <li key={i}>{r}</li>)}
              </ul>
            </div>
          )}

          <div className="bg-white border border-gray-200 rounded-xl divide-y divide-gray-100">
            {report.items.map((it, i) => (
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
        </div>
      )}
    </div>
  )
}
