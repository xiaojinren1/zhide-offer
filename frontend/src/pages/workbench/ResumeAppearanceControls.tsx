import { useRef, useState } from 'react'
import { api } from '../../lib/api'
import ResumePreview, { defaultResumeAppearance, type ResumeAppearance } from './ResumePreview'
import { operationError } from './state'

const templates = [
  { value: 'classic', label: '经典单栏' },
  { value: 'sidebar', label: '现代侧栏' },
  { value: 'compact', label: '简洁紧凑' },
] as const

const colors = [
  { key: 'background', label: '页面背景' },
  { key: 'paper', label: '纸张背景' },
  { key: 'accent', label: '章节标题颜色' },
] as const

export function readResumeTemplate(text: string): ResumeAppearance | null {
  try {
    const file = JSON.parse(text)
    if (file?.version !== 1) return null
    const style = file.appearance
    if (!style || !templates.some(option => option.value === style.template)
      || !colors.every(({ key }) => typeof style[key] === 'string' && /^#[0-9a-f]{6}$/i.test(style[key]))
      || ![13, 14, 16].includes(style.fontSize) || ![1.35, 1.6, 1.85].includes(style.spacing)) return null
    const { template, background, paper, accent, fontSize, spacing } = style
    const { headerAlign, sidebarSide, headerStyle } = style
    if (headerAlign !== undefined && !['left', 'center'].includes(headerAlign)) return null
    if (sidebarSide !== undefined && !['left', 'right'].includes(sidebarSide)) return null
    if (headerStyle !== undefined && !['standard', 'portrait'].includes(headerStyle)) return null
    const { nameColor, headingFont } = style
    if (nameColor != null && (typeof nameColor !== 'string' || !/^#[0-9a-f]{6}$/i.test(nameColor))) return null
    if (headingFont !== undefined && !['sans', 'serif'].includes(headingFont)) return null
    return { template, background, paper, accent, fontSize, spacing, headerAlign, sidebarSide, headerStyle, nameColor, headingFont }
  } catch {
    return null
  }
}

function downloadTemplate(appearance: ResumeAppearance) {
  const { portrait: _portrait, ...layout } = appearance
  const blob = new Blob([JSON.stringify({ version: 1, appearance: layout }, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = 'resume-template.json'
  link.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

async function preparePortrait(file: File): Promise<string> {
  const bitmap = await createImageBitmap(file)
  try {
    const canvas = document.createElement('canvas')
    canvas.width = 180
    canvas.height = 252
    const context = canvas.getContext('2d')
    if (!context) throw new Error('无法处理证件照')
    context.fillStyle = '#fff'
    context.fillRect(0, 0, canvas.width, canvas.height)
    const scale = Math.max(canvas.width / bitmap.width, canvas.height / bitmap.height)
    const width = bitmap.width * scale
    const height = bitmap.height * scale
    context.drawImage(bitmap, (canvas.width - width) / 2, (canvas.height - height) / 2, width, height)
    return canvas.toDataURL('image/jpeg', 0.8)
  } finally {
    bitmap.close()
  }
}

export default function ResumeAppearanceControls({ markdown, appearance, onChange }: {
  markdown: string
  appearance: ResumeAppearance
  onChange: (value: ResumeAppearance) => void
}) {
  const fileInput = useRef<HTMLInputElement>(null)
  const portraitInput = useRef<HTMLInputElement>(null)
  const latestAppearance = useRef(appearance)
  latestAppearance.current = appearance
  const [loadingPortrait, setLoadingPortrait] = useState(false)
  const [importing, setImporting] = useState(false)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [suggestion, setSuggestion] = useState<ResumeAppearance | null>(null)

  async function importTemplate(file: File) {
    setNotice('')
    setError('')
    setSuggestion(null)
    const image = /\.(png|jpe?g|webp)$/i.test(file.name)
    const limit = image ? 10 * 1024 * 1024 : 16 * 1024
    if (file.size > limit) {
      setError(image ? '参考图片不能超过 10 MB。' : '模板文件不能超过 16 KB。')
      return
    }
    if (image && !window.confirm('参考图会发送给你配置的图片模型服务商识别版式。请先遮盖姓名、电话和邮箱等信息。继续识别？')) return
    setImporting(true)
    try {
      if (image) {
        setSuggestion(await api.recognizeResumeTemplate(file))
        return
      }
      const imported = readResumeTemplate(await file.text())
      if (!imported) {
        setError('模板格式无效，请选择兼容的简历模板 JSON 文件。')
        return
      }
      onChange({ ...imported, portrait: appearance.portrait })
      setNotice('模板已应用到当前预览。')
    } catch (reason) {
      setError(image ? operationError(reason) : '读取模板失败，请重新选择文件。')
    } finally {
      setImporting(false)
    }
  }

  return <div className="resume-appearance-controls">
    <fieldset>
      <legend>简历模板</legend>
      <div className="resume-template-options">
        {templates.map(({ value, label }) => <button key={value} type="button" aria-pressed={appearance.template === value}
          onClick={() => onChange({ ...appearance, template: value })}>
          <span className="resume-template-thumbnail" data-template={value} aria-hidden="true"><i /><i /><i /></span>
          {label}
        </button>)}
      </div>
      <div className="resume-template-file-actions">
        <button type="button" className="secondary-button" disabled={importing}
          onClick={() => fileInput.current?.click()}>{importing ? '正在读取…' : '导入模板'}</button>
        <input hidden ref={fileInput} type="file" accept=".json,.png,.jpg,.jpeg,.webp" onChange={event => {
            const file = event.currentTarget.files?.[0]
            event.currentTarget.value = ''
            if (file) void importTemplate(file)
        }} />
        <button type="button" className="secondary-button" onClick={() => downloadTemplate(appearance)}>导出当前模板</button>
      </div>
      <p className="field-hint">可选择职得模板文件，或用 PNG、JPG、WebP 简历截图识别相近版式。截图识别需要启用图片模型。</p>
      {suggestion && <section aria-label="识别版式预览">
        <p>识别结果 · {templates.find(option => option.value === suggestion.template)?.label}
          {suggestion.template === 'sidebar' && (suggestion.sidebarSide === 'right' ? ' · 右侧栏' : ' · 左侧栏')}
          {suggestion.headerAlign === 'center' ? ' · 标题居中' : ' · 标题靠左'}</p>
        <div className="resume-preview-canvas" style={{ backgroundColor: suggestion.background }}>
          <ResumePreview markdown={markdown} appearance={{ ...suggestion, portrait: appearance.portrait }} />
        </div>
        <div className="resume-template-file-actions">
          <button type="button" className="primary-button" onClick={() => {
            onChange({ ...suggestion, portrait: appearance.portrait })
            setSuggestion(null)
            setNotice('识别版式已应用。')
          }}>应用版式</button>
          <button type="button" className="secondary-button" onClick={() => setSuggestion(null)}>取消</button>
        </div>
      </section>}
      {error && <p className="warning-note" role="alert">{error}</p>}
      {notice && <p className="wb-success" role="status">{notice}</p>}
    </fieldset>
    <fieldset>
      <legend>外观</legend>
      <div className="resume-appearance-fields">
        <label>姓名颜色
          <input type="color" value={appearance.nameColor ?? appearance.accent}
            onChange={event => onChange({ ...appearance, nameColor: event.target.value })} />
        </label>
        <label>标题字体
          <select value={appearance.headingFont ?? 'sans'} onChange={event =>
            onChange({ ...appearance, headingFont: event.target.value === 'serif' ? 'serif' : 'sans' })}>
            <option value="sans">黑体风格</option><option value="serif">宋体风格</option>
          </select>
        </label>
        <label>页眉布局
          <select value={appearance.headerStyle ?? 'standard'} onChange={event =>
            onChange({ ...appearance, headerStyle: event.target.value === 'portrait' ? 'portrait' : 'standard' })}>
            <option value="standard">普通页眉</option><option value="portrait">证件照页眉</option>
          </select>
        </label>
        <label>标题对齐
          <select value={appearance.headerAlign ?? 'left'} onChange={event =>
            onChange({ ...appearance, headerAlign: event.target.value === 'center' ? 'center' : 'left' })}>
            <option value="left">靠左</option><option value="center">居中</option>
          </select>
        </label>
        {appearance.template === 'sidebar' && <label>侧栏位置
          <select value={appearance.sidebarSide ?? 'left'} onChange={event =>
            onChange({ ...appearance, sidebarSide: event.target.value === 'right' ? 'right' : 'left' })}>
            <option value="left">左侧</option><option value="right">右侧</option>
          </select>
        </label>}
        {colors.map(({ key, label }) => <label key={key}>{label}
          <input type="color" value={appearance[key]} onChange={event => onChange({ ...appearance, [key]: event.target.value })} />
        </label>)}
        <label>字号
          <select value={appearance.fontSize} onChange={event => onChange({ ...appearance, fontSize: Number(event.target.value) })}>
            <option value={13}>小</option><option value={14}>标准</option><option value={16}>大</option>
          </select>
        </label>
        <label>行距
          <select value={appearance.spacing} onChange={event => onChange({ ...appearance, spacing: Number(event.target.value) })}>
            <option value={1.35}>紧凑</option><option value={1.6}>标准</option><option value={1.85}>宽松</option>
          </select>
        </label>
        <button type="button" className="secondary-button" onClick={() => onChange({ ...defaultResumeAppearance, portrait: appearance.portrait })}>恢复默认</button>
      </div>
      <div className="resume-template-file-actions">
        <button type="button" className="secondary-button" disabled={loadingPortrait}
          onClick={() => portraitInput.current?.click()}>
          {loadingPortrait ? '正在处理证件照…' : appearance.portrait ? '更换证件照' : '上传证件照'}
        </button>
        <input hidden ref={portraitInput} type="file" accept=".png,.jpg,.jpeg,.webp" onChange={async event => {
            const file = event.currentTarget.files?.[0]
            event.currentTarget.value = ''
            if (!file) return
            setError('')
            if (!/\.(png|jpe?g|webp)$/i.test(file.name) || file.size > 5 * 1024 * 1024) {
              setError('请选择 5 MB 以内的 JPG、PNG 或 WebP 证件照。')
              return
            }
            setLoadingPortrait(true)
            try {
              const portrait = await preparePortrait(file)
              onChange({ ...latestAppearance.current, headerStyle: 'portrait', portrait })
            } catch {
              setError('证件照读取失败，请重新选择。')
            } finally {
              setLoadingPortrait(false)
            }
          }} />
        {appearance.portrait && <button type="button" className="secondary-button" disabled={loadingPortrait} onClick={() =>
          onChange({ ...appearance, portrait: null })}>移除证件照</button>}
      </div>
    </fieldset>
  </div>
}
