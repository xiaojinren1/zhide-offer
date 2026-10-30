import { useState } from 'react'
import { api } from '../lib/api'
import type { ResumeProfile } from '../lib/types'

interface Props {
  jdText: string
  jdKeywords: string[]
  profile: ResumeProfile | null
  markdown: string
  setMarkdown: (s: string) => void
}

export default function ResumePage({ jdText, jdKeywords, profile, markdown, setMarkdown }: Props) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [untraceable, setUntraceable] = useState<string[]>([])
  const [passed, setPassed] = useState<boolean | null>(null)
  const [slimming, setSlimming] = useState<{ total: number; used: number; dropped: string[] } | null>(null)

  const run = async () => {
    if (!profile || !jdText.trim()) return
    setBusy(true); setError('')
    try {
      const r = await api.generateResume(jdText, profile, jdKeywords)
      if (r.ok && r.markdown) {
        setMarkdown(r.markdown)
        setUntraceable(r.untraceable || [])
        setPassed(r.traceability_passed ?? true)
        setSlimming(r.slimming || null)
      } else setError(r.error || '生成失败')
    } catch (e) { setError(String(e)) } finally { setBusy(false) }
  }

  return (
    <div className="space-y-5">
      <header>
        <h2 className="text-lg font-medium">第三步 · 定制简历生成</h2>
        <p className="text-sm text-gray-500 mt-1">
          按 JD 重写经历表述（STAR + 量化），只改写排序、不新增事实。
        </p>
      </header>

      <button onClick={run} disabled={busy || !profile || !jdText.trim()}
        className="px-5 py-2 bg-teal-600 text-white rounded-lg disabled:bg-gray-300">
        {busy ? '生成中：写稿 → 自检 → 修订（最多约 150 秒）…' : '生成定制简历'}
      </button>
      {busy && (
        <p className="text-xs text-gray-500">
          正在跑"生成 → 质检工具自检 → 按问题修订"循环；超时会返回当前最好的一版，不会无限等待。
        </p>
      )}
      {error && <p className="text-sm text-red-600">{error}</p>}

      {markdown && (
        <div className="space-y-3">
          {slimming && slimming.total > slimming.used && (
            <p className="text-xs text-gray-500">
              已按 JD 相关度挑出 {slimming.used}/{slimming.total} 段经历生成（省 token、聚焦匹配点）；
              未使用：{slimming.dropped.join('、')}
            </p>
          )}
          <div className={`rounded-xl p-3 text-sm border ${
            passed ? 'bg-green-50 border-green-200 text-green-800' : 'bg-red-50 border-red-200 text-red-800'
          }`}>
            {passed
              ? '可追溯校验通过：抽样陈述均可回溯到经历库'
              : `发现 ${untraceable.length} 条不可回溯陈述（疑似虚构），请人工删除或改回经历库事实：`}
            {!passed && (
              <ul className="mt-2 space-y-1 list-disc pl-5 text-xs">
                {untraceable.map((u, i) => <li key={i}>{u}</li>)}
              </ul>
            )}
          </div>
          <pre className="bg-white border border-gray-200 rounded-xl p-4 text-sm whitespace-pre-wrap font-sans">
            {markdown}
          </pre>
        </div>
      )}
    </div>
  )
}
