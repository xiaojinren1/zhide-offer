import { useEffect, useRef, useState } from 'react'
import { api, apiErrorMessage } from '../lib/api'
import type { TextModelPreference } from '../lib/api'
import { clearLegacyModel } from '../lib/modelStorage'

export default function ModelPreferences({ userId }: { userId: string }) {
  const secure = window.isSecureContext
  const [active, setActive] = useState<TextModelPreference | null>(null)
  const [baseUrl, setBaseUrl] = useState('')
  const [models, setModels] = useState<string[]>([])
  const [modelListStatus, setModelListStatus] = useState('')
  const [model, setModel] = useState('')
  const [revealedKey, setRevealedKey] = useState<string | null>(null)
  const revealGeneration = useRef(0)
  const keyEye = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    const hide = () => {
      revealGeneration.current++
      setRevealedKey(null)
    }
    const hideOutside = (event: PointerEvent) => {
      if (event.target instanceof Node && !keyEye.current?.contains(event.target)) hide()
    }
    window.addEventListener('pointerdown', hideOutside)
    window.addEventListener('blur', hide)
    return () => {
      window.removeEventListener('pointerdown', hideOutside)
      window.removeEventListener('blur', hide)
      revealGeneration.current++
    }
  }, [])
  const [key, setKey] = useState('')
  const [busy, setBusy] = useState(true)
  const [success, setSuccess] = useState('')
  const [error, setError] = useState('')
  useEffect(() => {
    let live = true
    api.modelPreference().then(value => {
      if (!live) return
      setActive(value)
      const saved = value
      if (saved) {
        setBaseUrl(saved.base_url)
        setModel(saved.model)
      }
    }).catch(reason => { if (live) setError(apiErrorMessage(reason)) })
      .finally(() => { if (live) setBusy(false) })
    return () => { live = false }
  }, [secure, userId])

  const savedUrl = active?.base_url
  const canReuseKey = Boolean(active?.has_api_key && savedUrl === baseUrl.trim().replace(/\/+$/, ''))
  const connection = { provider: canReuseKey && active ? active.provider : 'custom' as const, base_url: baseUrl.trim(), api_key: key }
  const canConnect = Boolean(baseUrl.trim() && (key.trim() || canReuseKey))

  function clearModels() {
    setModels([])
    setModelListStatus('')
  }

  function hideKey() {
    revealGeneration.current++
    setRevealedKey(null)
  }

  async function revealKey() {
    const generation = ++revealGeneration.current
    if (key) {
      setRevealedKey('')
      return
    }
    try {
      const result = await api.revealModelKey()
      if (generation === revealGeneration.current) setRevealedKey(result.api_key)
    } catch (reason) {
      if (generation === revealGeneration.current) setError(apiErrorMessage(reason))
    }
  }

  async function fetchModels() {
    if (busy) return
    hideKey()
    setBusy(true)
    setError('')
    setSuccess('')
    clearModels()
    try {
      const result = await api.listModels(connection)
      setModels(result.models)
      setModelListStatus(result.models.length ? `获取到 ${result.models.length} 个模型` : '服务商未返回模型，可以手动填写模型 ID。')
    } catch (reason) {
      setError(apiErrorMessage(reason))
    } finally {
      setBusy(false)
    }
  }

  async function update(reset: boolean) {
    if (busy) return
    hideKey()
    setBusy(true)
    setError('')
    setSuccess('')
    try {
      if (reset) {
        await api.resetModel()
        clearLegacyModel(userId)
        setActive(null)
        setBaseUrl('')
        setModel('')
        clearModels()
        setSuccess('已恢复平台默认模型。')
      } else {
        const result = await api.activateModel({ ...connection, model: model.trim() })
        setActive(result)
        setBaseUrl(result.base_url)
        clearLegacyModel(userId)
        setSuccess(`测试成功，已启用 ${result.model}。当前账号的文本任务将使用此模型。`)
      }
      setKey('')
      setRevealedKey(null)
    } catch (reason) {
      setError(apiErrorMessage(reason))
    } finally {
      setBusy(false)
    }
  }

  return <section className="panel" aria-label="个人文本模型">
    <h2>个人文本模型</h2>
    <p role="status">{active ? `已启用 ${active.model}` : '使用平台默认模型'}</p>
    <p>启用后，文本求职材料会发送给选定服务商。配置按账户保存，换设备登录也可使用。API Key 加密保存，服务端调用时会解密并使用。</p>
    {!secure && <p>请通过 HTTPS 打开站点后填写 API Key。</p>}
    <div role="group" aria-label="模型连接配置">
      <fieldset disabled={busy || !secure}>
        <label htmlFor="model-base-url">Base URL</label>
        <input id="model-base-url" type="url" value={baseUrl} maxLength={512} required
          placeholder="https://api.example.com/v1" onChange={event => { setBaseUrl(event.target.value); hideKey(); clearModels() }} />
        <p className="field-hint">填写管理员已允许的 HTTPS Base URL，例如以 /v1 结尾的地址。</p>
        <label htmlFor="model-api-key">API Key</label>
        <div className="model-key-field">
          <input id="model-api-key" type={revealedKey === null ? 'password' : 'text'} autoComplete="off" autoCapitalize="none" spellCheck={false}
            value={key || (canReuseKey ? revealedKey ?? '' : '')} maxLength={512}
            placeholder={canReuseKey ? '••••••••（已保存）' : '请输入 API Key'}
            onChange={event => { setKey(event.target.value); clearModels() }} />
          <button type="button" ref={keyEye} className="model-key-eye" aria-label="查看 API Key" aria-pressed={revealedKey !== null}
            disabled={!key && !canReuseKey} onClick={() => { if (revealedKey === null) void revealKey(); else hideKey() }} onPointerLeave={hideKey} onBlur={hideKey}
            onKeyDown={event => { if (event.key === 'Escape') hideKey() }}>
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
              <path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12Z" /><circle cx="12" cy="12" r="2.5" />
              {revealedKey === null && <path d="m4 4 16 16" />}
            </svg>
          </button>
        </div>
        <button type="button" className="secondary-button" disabled={!canConnect} onClick={() => void fetchModels()}>获取模型列表</button>
        {modelListStatus && <p role="status">{modelListStatus}</p>}
        {models.length > 0 && <><label htmlFor="model-list">从列表选模型</label><select id="model-list" value={models.includes(model) ? model : ''} onChange={event => setModel(event.target.value)}>
          <option value="">请选择</option>{models.map(id => <option key={id} value={id}>{id}</option>)}
        </select></>}
        <label htmlFor="model-id">模型 ID（可手动填写）</label>
        <input id="model-id" value={model} maxLength={120} required onChange={event => setModel(event.target.value)} />
        <button type="button" className="primary-button" disabled={!canConnect || !model.trim()} onClick={() => void update(false)}>测试并启用</button>
        {(active || key) && <button type="button" className="secondary-button" onClick={() => void update(true)}>恢复默认模型</button>}
      </fieldset>
    </div>
    {success && <p role="status">{success}</p>}
    {error && <p role="alert">{error}</p>}
  </section>
}
