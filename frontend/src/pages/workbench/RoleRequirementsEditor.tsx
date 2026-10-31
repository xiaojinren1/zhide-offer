import { useEffect, useRef, useState } from 'react'
import { api } from '../../lib/api'
import { operationError } from './state'

interface Props {
  id: string
  jdText: string
  onChange: (value: string) => void
  disabled?: boolean
  onBusyChange?: (value: boolean) => void
}

export default function RoleRequirementsEditor({ id, jdText, onChange, disabled = false, onBusyChange }: Props) {
  const [jobTitle, setJobTitle] = useState('')
  const [generating, setGenerating] = useState(false)
  const [preview, setPreview] = useState('')
  const [previewInput, setPreviewInput] = useState('')
  const [error, setError] = useState('')
  const snapshot = JSON.stringify([jobTitle, jdText])
  const latestInput = useRef(snapshot)
  latestInput.current = snapshot
  const locked = useRef(false)
  const mounted = useRef(true)
  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false }
  }, [])
  const isDisabled = disabled || generating
  const visiblePreview = previewInput === snapshot

  const generate = async () => {
    if (locked.current || disabled || !jobTitle.trim()) return
    if (jobTitle.trim().length > 120) { setError('岗位名称不能超过 120 字。'); return }
    const input = snapshot
    locked.current = true
    setGenerating(true); onBusyChange?.(true); setError(''); setPreviewInput('')
    try {
      const result = await api.generateRole(jobTitle.trim())
      if (!mounted.current || latestInput.current !== input) return
      if (!result.ok || typeof result.jd_text !== 'string' || !result.jd_text.trim()) {
        throw new Error(result.error || '模型未返回岗位职责与要求，请重试。')
      }
      setPreview(result.jd_text); setPreviewInput(input)
    } catch (reason) {
      if (mounted.current && latestInput.current === input) setError(operationError(reason))
    } finally {
      locked.current = false
      if (mounted.current) { setGenerating(false); onBusyChange?.(false) }
    }
  }

  return <div className="role-requirements-editor">
    <label className="field-label" htmlFor={`${id}-title`}>你想应聘什么岗位？</label>
    <div className="role-title-actions">
      <input id={`${id}-title`} value={jobTitle} disabled={isDisabled} maxLength={120}
        onChange={e => { setJobTitle(e.target.value); setPreviewInput(''); setError('') }} placeholder="例如：嵌入式开发工程师" />
      <button type="button" className="secondary-button" disabled={isDisabled || !jobTitle.trim()} onClick={generate}>
        {generating ? '正在生成岗位参考…' : 'AI 生成职责与要求'}
      </button>
    </div>
    <p className="wb-hint">按岗位名称生成通用职责与技能参考，非具体企业 JD，也不是实时招聘检索；不会默认设定学历、年限或证书门槛。请核对后采用。</p>
    {error && <div className="error-banner" role="alert">{error}</div>}
    {visiblePreview && <section className="role-reference-preview" aria-label="岗位参考预览">
      <h3>岗位参考预览</h3>
      <p className="wb-hint">可编辑、删除或补充职责。采用后更新下方岗位要求，保留当前简历和事实确认；旧报告需要重新运行。</p>
      <textarea aria-label="编辑岗位参考" value={preview} disabled={isDisabled} onChange={e => setPreview(e.target.value)} />
      <div className="wb-actions">
        <button type="button" className="primary-button" disabled={isDisabled || !preview.trim()} onClick={() => {
          if (isDisabled || !preview.trim() || !visiblePreview) return
          onChange(preview.trim()); setPreviewInput(''); setError('')
        }}>采用岗位要求</button>
        <button type="button" className="secondary-button" disabled={isDisabled} onClick={() => setPreviewInput('')}>放弃参考</button>
      </div>
    </section>}
    <label className="field-label" htmlFor={id}>岗位职责与任职要求</label>
    <textarea id={id} className="jd-text" value={jdText} disabled={isDisabled}
      onChange={e => { onChange(e.target.value); setPreviewInput(''); setError('') }}
      placeholder="可采用上方参考后补充职责，也可直接粘贴完整的真实 JD。" />
  </div>
}
