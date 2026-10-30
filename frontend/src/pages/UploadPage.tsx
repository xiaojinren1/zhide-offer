import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import type { ResumeProfile } from '../lib/types'

interface Props {
  profile: ResumeProfile | null
  onConfirm: (p: ResumeProfile) => void
}

interface SavedProfile {
  id: string
  name: string
  saved_at: string
  experience_count: number
}

export default function UploadPage({ profile, onConfirm }: Props) {
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState<SavedProfile[]>([])
  const [saveMsg, setSaveMsg] = useState('')

  const loadSaved = async () => {
    const r = await api.listProfiles()
    if (r.ok) setSaved(r.profiles || [])
  }

  useEffect(() => { loadSaved() }, [])

  const run = async (fn: () => Promise<{ ok: boolean; error?: string; profile?: ResumeProfile }>) => {
    setBusy(true); setError('')
    try {
      const r = await fn()
      if (r.ok && r.profile) onConfirm({ ...r.profile, user_confirmed: false })
      else setError(r.error || '解析失败')
    } catch (e) { setError(String(e)) } finally { setBusy(false) }
  }

  const save = async () => {
    if (!profile) return
    setSaveMsg('')
    const r = await api.saveProfile(profile.name || '未命名', { ...profile, user_confirmed: true })
    setSaveMsg(r.ok ? '已保存，下次可直接载入' : `保存失败：${r.error || ''}`)
    if (r.ok) loadSaved()
  }

  const loadOne = async (id: string) => {
    setBusy(true); setError('')
    try {
      const r = await api.loadProfile(id)
      if (r.ok && r.profile) onConfirm({ ...r.profile, user_confirmed: true })
      else setError(r.error || '载入失败')
    } catch (e) { setError(String(e)) } finally { setBusy(false) }
  }

  return (
    <div className="space-y-5">
      <header>
        <h2 className="text-lg font-medium">第一步 · 建立你的经历库</h2>
        <p className="text-sm text-gray-500 mt-1">
          上传现有简历自动解析（推荐），或直接粘贴文本。解析结果可人工修正后再确认。
        </p>
      </header>

      {saved.length > 0 && (
        <div className="bg-white border border-gray-200 rounded-xl p-4">
          <h3 className="text-sm font-medium">已保存的经历库（长期记忆）</h3>
          <ul className="mt-2 space-y-1.5">
            {saved.map((p) => (
              <li key={p.id} className="flex items-center justify-between text-sm">
                <span>
                  <span className="font-medium">{p.name || '未命名'}</span>
                  <span className="text-gray-500"> · {p.experience_count} 段经历 · {p.saved_at}</span>
                </span>
                <span className="flex gap-2">
                  <button onClick={() => loadOne(p.id)} disabled={busy}
                    className="text-teal-700 text-xs hover:underline disabled:opacity-40">载入</button>
                  <button onClick={async () => { await api.deleteProfile(p.id); loadSaved() }}
                    className="text-gray-400 text-xs hover:underline">删除</button>
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <label className="block border-2 border-dashed border-gray-300 rounded-xl p-8 text-center hover:border-teal-500 transition-colors cursor-pointer">
        <input type="file" accept=".pdf,.docx,.txt,.md" className="hidden" disabled={busy}
          onChange={(e) => { const f = e.target.files?.[0]; if (f) run(() => api.parseResumeFile(f)) }} />
        <div className="text-gray-600">{busy ? '解析中…' : '点击选择简历文件（pdf / docx / txt / md）'}</div>
      </label>

      <div className="flex gap-2">
        <textarea value={text} onChange={(e) => setText(e.target.value)}
          placeholder="或在此粘贴简历纯文本"
          className="flex-1 h-32 border border-gray-300 rounded-lg p-3 text-sm" />
        <button disabled={busy || !text.trim()} onClick={() => run(() => api.parseResumeText(text))}
          className="px-4 py-2 bg-teal-600 text-white rounded-lg disabled:bg-gray-300 self-start">
          解析文本
        </button>
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}

      {profile && (
        <div className="bg-white border border-gray-200 rounded-xl p-4">
          <div className="flex items-center justify-between">
            <h3 className="font-medium">解析结果 · {profile.experiences.length} 段经历</h3>
            <span className="flex gap-2">
              <button onClick={save} className="px-3 py-1.5 border border-teal-600 text-teal-700 text-sm rounded-lg">
                保存经历库
              </button>
              <button onClick={() => onConfirm({ ...profile, user_confirmed: true })}
                className="px-4 py-1.5 bg-teal-600 text-white text-sm rounded-lg">
                确认并继续
              </button>
            </span>
          </div>
          {saveMsg && <p className="text-xs text-teal-700 mt-1">{saveMsg}</p>}
          <ul className="mt-3 space-y-2 text-sm">
            {profile.experiences.map((e, i) => (
              <li key={i} className="border-l-2 border-teal-400 pl-3">
                <span className="font-medium">{e.name}</span>
                <span className="text-gray-500"> · {e.role} · {e.period}</span>
                <div className="text-gray-600 mt-0.5">行动 {e.actions.length} 条 / 结果 {e.results.length} 条</div>
              </li>
            ))}
          </ul>
          {profile.skills.length > 0 && (
            <p className="text-sm text-gray-600 mt-3">技能：{profile.skills.join('、')}</p>
          )}
        </div>
      )}
    </div>
  )
}
