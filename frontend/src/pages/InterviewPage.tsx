import { useState } from 'react'
import { api } from '../lib/api'
import type { ResumeProfile, Suspicion } from '../lib/types'

interface Props {
  jdText: string
  profile: ResumeProfile | null
  markdown: string
}

export default function InterviewPage({ jdText, profile, markdown }: Props) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [questions, setQuestions] = useState<Array<{
    question: string; trap: string; answer_key: string; source_suspicion: string
  }>>([])
  const [suspicions, setSuspicions] = useState<Suspicion[]>([])

  const run = async () => {
    if (!profile || !markdown.trim()) return
    setBusy(true); setError('')
    try {
      const r = await api.interview(markdown, profile, jdText)
      if (r.ok) { setQuestions(r.questions || []); setSuspicions(r.suspicions || []) }
      else setError(r.error || '预演失败')
    } catch (e) { setError(String(e)) } finally { setBusy(false) }
  }

  return (
    <div className="space-y-5">
      <header>
        <h2 className="text-lg font-medium">第五步 · 面试预演</h2>
        <p className="text-sm text-gray-500 mt-1">
          AI 当面试官，只挖你简历里可复核的坑——没有基数、无法归因、时间重叠、技能无支撑。
        </p>
      </header>

      <button onClick={run} disabled={busy || !profile || !markdown.trim()}
        className="px-5 py-2 bg-teal-600 text-white rounded-lg disabled:bg-gray-300">
        {busy ? '准备中…' : '开始预演'}
      </button>
      {error && <p className="text-sm text-red-600">{error}</p>}

      {questions.length > 0 && (
        <ol className="space-y-3">
          {questions.map((q, i) => (
            <li key={i} className="bg-white border border-gray-200 rounded-xl p-4">
              <div className="flex gap-2">
                <span className="text-sm font-medium text-gray-400">Q{i + 1}</span>
                <p className="text-sm font-medium flex-1">{q.question}</p>
              </div>
              <p className="text-xs text-red-600 mt-2">坑：{q.trap}</p>
              <p className="text-xs text-gray-500 mt-0.5">疑点类型：{q.source_suspicion}</p>
              <p className="text-sm text-teal-700 mt-2">答题要点：{q.answer_key}</p>
            </li>
          ))}
        </ol>
      )}

      {suspicions.length > 0 && (
        <details className="bg-white border border-gray-200 rounded-xl p-4">
          <summary className="text-sm font-medium cursor-pointer">
            本次依据的疑点清单（{suspicions.length} 条，全部程序可判）
          </summary>
          <ul className="mt-2 space-y-1 text-xs text-gray-600 list-disc pl-5">
            {suspicions.map((x, i) => <li key={i}>[{x.type}] {x.detail}</li>)}
          </ul>
        </details>
      )}
    </div>
  )
}
