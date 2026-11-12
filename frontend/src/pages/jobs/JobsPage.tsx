import { useCallback, useEffect, useRef, useState } from 'react'
import { apiErrorMessage, applicationsApi, jobsApi, jobsFetchAllApi, jobsPasteApi, jobsProvinceApi, jobsSourceApi } from '../../lib/api'
import type { ApplicationStage, JobApplication, JobDocument, JobProvince, JobSource, PasteGuess } from '../../lib/api'
import './jobs.css'

interface Props {
  userId: string
  disabled: boolean
  canManage: boolean
  onUseJd: (text: string, title: string) => void
}

interface ImportForm {
  text: string
  title: string
  company: string
  city: string
  salary: string
  url: string
  source: 'paste' | 'image'
  parse: boolean
}

const emptyForm: ImportForm = {
  text: '', title: '', company: '', city: '', salary: '', url: '', source: 'paste', parse: true,
}

interface SourceForm {
  id: string
  name: string
  kind: 'rss' | 'html_list'
  url: string
  tier: string
  license_note: string
  config: string
}

const emptySourceForm: SourceForm = {
  id: '', name: '', kind: 'html_list', url: '', tier: '1', license_note: '',
  config: '{\n  "include_keywords": ["招聘", "公告"],\n  "max_items": 10,\n  "fetch_detail": true\n}',
}

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []
}

function salaryLine(doc: JobDocument): string {
  if (doc.salary_text) return doc.salary_text
  if (doc.salary_min && doc.salary_max) return `${Math.round(doc.salary_min / 1000)}-${Math.round(doc.salary_max / 1000)}K`
  return ''
}

function subtitle(doc: JobDocument): string {
  return [doc.company, doc.city].filter(Boolean).join(' · ') || '未填写公司'
}

const APPLICATION_STAGE_LABEL: Record<ApplicationStage, string> = {
  saved: '已收藏',
  tailored: '已定制简历',
  applied: '已投递',
  interview: '面试中',
  offer: '拿到 offer',
  rejected: '被拒',
  archived: '已归档',
}

const SOURCE_LABELS: Record<string, string> = {
  feed: '信源采集', paste: '粘贴文本', image: '截图转写', upload: '上传文件', manual: '手工录入',
}

export default function JobsPage({ userId, disabled, canManage, onUseJd }: Props) {
  const [items, setItems] = useState<JobDocument[]>([])
  const [selected, setSelected] = useState<JobDocument | null>(null)
  const [chunkCount, setChunkCount] = useState(0)
  const [query, setQuery] = useState('')
  const [form, setForm] = useState<ImportForm>(emptyForm)
  const [showForm, setShowForm] = useState(false)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [sources, setSources] = useState<JobSource[]>([])
  const [showSources, setShowSources] = useState(false)
  const [sourceForm, setSourceForm] = useState<SourceForm>(emptySourceForm)
  const [sourceBusy, setSourceBusy] = useState('')
  const [provinces, setProvinces] = useState<JobProvince[]>([])
  const [provinceCode, setProvinceCode] = useState('')
  const [provinceUrl, setProvinceUrl] = useState('')
  const [guess, setGuess] = useState<{ fields: PasteGuess; duplicate: { id: string; title: string } | null } | null>(null)
  const [imageBusy, setImageBusy] = useState(false)
  // 投递看板：doc_id -> 当前阶段；筛选与详情都要用
  const [applications, setApplications] = useState<Record<string, JobApplication>>({})
  const [application, setApplication] = useState<JobApplication | null>(null)
  const [appNote, setAppNote] = useState('')
  const [appDate, setAppDate] = useState('')
  const [stageFilter, setStageFilter] = useState<'' | ApplicationStage>('')
  const [busyStage, setBusyStage] = useState('')
  const imageInput = useRef<HTMLInputElement>(null)
  const analysisSeq = useRef(0)

  // 粘贴后自动识别：只补空字段，用户已经改了的不覆盖；停手 600ms 才发请求
  useEffect(() => {
    const body = form.text.trim()
    if (body.length < 40) {
      setGuess(null)
      return
    }
    const seq = ++analysisSeq.current
    const timer = setTimeout(() => {
      jobsPasteApi.analyze(body).then(result => {
        if (seq !== analysisSeq.current) return
        setGuess({ fields: result.guess, duplicate: result.duplicate })
        setForm(previous => ({
          ...previous,
          title: previous.title || result.guess.title || '',
          company: previous.company || result.guess.company || '',
          city: previous.city || result.guess.city || '',
          salary: previous.salary || result.guess.salary_text || '',
          url: previous.url || result.guess.url || '',
        }))
      }).catch(() => { /* 识别失败不打扰用户，手动填即可 */ })
    }, 600)
    return () => clearTimeout(timer)
  }, [form.text])

  const refresh = useCallback(async (keyword: string) => {
    setLoading(true)
    setError('')
    try {
      const result = await jobsApi.list(keyword.trim() ? { q: keyword.trim() } : {})
      setItems(result.items)
    } catch (reason) {
      setError(apiErrorMessage(reason))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void refresh('') }, [refresh, userId, canManage])

  const loadSources = useCallback(async () => {
    if (!canManage) return
    try {
      const result = await jobsSourceApi.list()
      setSources(result.items)
    } catch (reason) {
      setError(apiErrorMessage(reason))
    }
  }, [canManage])

  useEffect(() => { void loadSources() }, [loadSources])

  const loadProvinces = useCallback(async () => {
    if (!canManage) return
    try {
      const result = await jobsProvinceApi.list()
      setProvinces(result.items)
    } catch (reason) {
      setError(apiErrorMessage(reason))
    }
  }, [canManage])

  useEffect(() => { void loadProvinces() }, [loadProvinces])

  const loadApplications = useCallback(async () => {
    try {
      const result = await applicationsApi.list({ include_archived: true })
      setApplications(Object.fromEntries(result.items.map(item => [item.doc_id, item])))
    } catch {
      setApplications({})
    }
  }, [])

  useEffect(() => { void loadApplications() }, [loadApplications, userId])

  const selectedProvince = provinces.find(item => item.code === provinceCode) || null

  async function toggleProvince() {
    if (!canManage || !provinceCode || sourceBusy) return
    setSourceBusy(`province-${provinceCode}`)
    setError('')
    try {
      if (selectedProvince?.enabled) {
        await jobsProvinceApi.disable(provinceCode)
        setNotice(`已停用 ${selectedProvince.name}的信源`)
      } else {
        const result = await jobsProvinceApi.enable(provinceCode, provinceUrl.trim())
        setNotice(`已启用 ${result.name}，在下方列表点「试抓」开始采集`)
      }
      await loadProvinces()
      await loadSources()
    } catch (reason) {
      setError(apiErrorMessage(reason))
    } finally {
      setSourceBusy('')
    }
  }

  async function saveSource() {
    if (!canManage || sourceBusy) return
    let config: Record<string, unknown>
    try {
      config = sourceForm.config.trim() ? JSON.parse(sourceForm.config) : {}
    } catch {
      setError('配置需要是合法 JSON')
      return
    }
    setSourceBusy('save')
    setError('')
    try {
      await jobsSourceApi.save({
        id: sourceForm.id.trim(), name: sourceForm.name.trim(), kind: sourceForm.kind,
        url: sourceForm.url.trim(), tier: Number(sourceForm.tier) || 3,
        license_note: sourceForm.license_note.trim(), config,
      })
      setSourceForm(emptySourceForm)
      setNotice('信源已保存')
      await loadSources()
    } catch (reason) {
      setError(apiErrorMessage(reason))
    } finally {
      setSourceBusy('')
    }
  }

  async function fetchAll() {
    if (!canManage || sourceBusy) return
    setSourceBusy('all')
    setError('')
    try {
      const result = await jobsFetchAllApi.all()
      const parts = [`抓取 ${result.sources} 个源：新增 ${result.created}，更新 ${result.updated}，跳过 ${result.skipped}`]
      if (result.failed) parts.push(`${result.failed} 个源失败（看列表里的状态）`)
      if (result.remaining) parts.push(`还有 ${result.remaining} 个源没跑完，再点一次继续`)
      setNotice(parts.join('；'))
      await loadSources()
      await loadProvinces()
      await refresh(query)
    } catch (reason) {
      setError(apiErrorMessage(reason))
    } finally {
      setSourceBusy('')
    }
  }

  async function fetchSource(id: string) {
    if (!canManage || sourceBusy) return
    setSourceBusy(id)
    setError('')
    try {
      const result = await jobsSourceApi.fetch(id)
      if (result.ok) {
        setNotice(`抓取完成：新增 ${result.created ?? 0} 条，更新 ${result.updated ?? 0} 条，跳过 ${result.skipped ?? 0} 条（${result.seconds ?? 0} 秒）`)
      } else {
        setError(`抓取失败：${result.error ?? '未知原因'}`)
      }
      await loadSources()
      await refresh(query)
    } catch (reason) {
      setError(apiErrorMessage(reason))
    } finally {
      setSourceBusy('')
    }
  }

  async function openDocument(id: string) {
    try {
      const result = await jobsApi.detail(id)
      setSelected(result.document)
      setChunkCount(result.chunks.length)
      const record = applications[id]
      setApplication(record || null)
      setAppNote(record?.note || '')
      setAppDate(record?.next_action_date || '')
      if (!record) {
        try {
          const detail = await applicationsApi.detail(id)
          setApplication(detail.application)
          setAppNote(detail.application.note)
          setAppDate(detail.application.next_action_date)
        } catch {
          /* 还没加入看板，保持空状态 */
        }
      }
    } catch (reason) {
      setError(apiErrorMessage(reason))
    }
  }

  /** 推进投递状态；第一次调用等价于「加入投递看板」。 */
  async function advanceApplication(stage: ApplicationStage) {
    if (!selected || disabled) return
    setBusyStage(stage)
    setError('')
    try {
      const result = await applicationsApi.advance(selected.id, {
        stage, note: appNote, next_action: appDate,
      })
      setApplication(result.application)
      setApplications(previous => ({ ...previous, [selected.id]: result.application }))
      setNotice(`已更新投递状态：${result.application.stage_label}`)
    } catch (reason) {
      setError(apiErrorMessage(reason))
    } finally {
      setBusyStage('')
    }
  }

  async function removeApplication() {
    if (!selected || disabled) return
    if (!window.confirm('把这个岗位移出投递看板？岗位资料本身不会被删除。')) return
    try {
      await applicationsApi.remove(selected.id)
      setApplication(null)
      setApplications(previous => {
        const next = { ...previous }
        delete next[selected.id]
        return next
      })
      setNotice('已移出投递看板')
    } catch (reason) {
      setError(apiErrorMessage(reason))
    }
  }

  async function submit() {
    if (disabled || saving) return
    if (!form.text.trim()) {
      setError('请先粘贴岗位 JD 或资料正文')
      return
    }
    setSaving(true)
    setError('')
    setNotice('')
    try {
      const result = await jobsApi.import({
        text: form.text,
        title: form.title,
        company: form.company,
        city: form.city,
        salary: form.salary,
        url: form.url,
        source: form.source,
        parse: form.parse,
      })
      setForm(emptyForm)
      setShowForm(false)
      setNotice(result.created ? '已存入收件箱' : '这份资料已在收件箱里，内容已更新')
      if (result.warnings.length) setError(result.warnings.join('；'))
      await refresh(query)
      await openDocument(result.id)
    } catch (reason) {
      setError(apiErrorMessage(reason))
    } finally {
      setSaving(false)
    }
  }

  function pickScreenshot() {
    if (disabled || saving || imageBusy) return
    imageInput.current?.click()
  }

  /** 截图导入第一步：只把图片读成文字并回填表单，绝不直接入库。 */
  async function uploadScreenshot(file: File) {
    if (disabled || saving || imageBusy) return
    const replace = form.text.trim() ? '识别结果会替换当前正文（没保存的内容会丢失）。' : ''
    const sent = '截图会发给你配置的图片模型服务商转写成文字，识别结果需要你核对后才会保存。继续？'
    if (!window.confirm(replace + sent)) return
    setImageBusy(true)
    setError('')
    setNotice('')
    try {
      const result = await jobsApi.parseImage(file)
      if (!result.ok || !result.text) {
        // 识别失败不写半成品：正文和字段都保持原样
        setError(result.error || '截图识别失败，请换一张更清晰的截图或直接粘贴文字')
        return
      }
      const fields = result.guess
      // 规则：识别到什么就是什么，没识别出的字段清空。
      // 不能“没识别出就保留上一次的值”——那会把上一份 JD 的薪资带到这一份上，
      // 用户看到的是一个不属于这个岗位的数字（比留空危险得多）。
      setForm(previous => ({
        ...previous,
        text: result.text || '',
        source: 'image',
        title: fields?.title || '',
        company: fields?.company || '',
        city: fields?.city || '',
        salary: fields?.salary_text || '',
        url: fields?.url || '',
      }))
      // 同一句提示可能同时来自字段识别和接口 warnings，去重后再展示
      const notices = Array.from(new Set(['截图已转写成文字，请核对正文与字段后再保存',
        ...(fields?.warnings || []), ...(result.warnings || [])]))
      setNotice(notices.join('；'))
    } catch (reason) {
      setError(apiErrorMessage(reason))
    } finally {
      setImageBusy(false)
      if (imageInput.current) imageInput.current.value = ''
    }
  }

  async function remove(id: string) {
    if (disabled) return
    try {
      await jobsApi.remove(id)
      if (selected?.id === id) setSelected(null)
      setNotice('已删除')
      await refresh(query)
    } catch (reason) {
      setError(apiErrorMessage(reason))
    }
  }

  return <div className="jobs-layout">
    <section className="panel jobs-list-panel" aria-labelledby="jobs-inbox-title">
      <div className="panel-heading">
        <h2 id="jobs-inbox-title">收件箱</h2>
        <button type="button" className="secondary-button" disabled={disabled}
          onClick={() => setShowForm(value => !value)}>
          {showForm ? '收起录入' : '录入岗位 / 资料'}
        </button>
        {canManage && <button type="button" className="secondary-button" disabled={disabled}
          onClick={() => setShowSources(value => !value)}>
          {showSources ? '收起信源' : '信源（管理员）'}
        </button>}
      </div>

      {showForm && <div className="jobs-form">
        <label>岗位 JD 或资料正文
          <textarea value={form.text} rows={8} disabled={disabled}
            placeholder="把 JD 全文粘进来（BOSS 直聘、智联这类平台：复制岗位详情文字即可）。会先自动识别岗位名、公司、城市、薪资，再保存。"
            onChange={event => setForm(previous => ({ ...previous, text: event.target.value }))} />
        </label>
        <div className="jobs-screenshot">
          <input ref={imageInput} type="file" hidden accept="image/png,image/jpeg,image/webp"
            onChange={event => {
              const file = event.target.files?.[0]
              if (file) void uploadScreenshot(file)
            }} />
          <button type="button" className="secondary-button" disabled={disabled || saving || imageBusy}
            onClick={pickScreenshot}>
            {imageBusy ? '识别中…' : '从截图导入'}
          </button>
          {form.source === 'image' && <span className="jobs-hint">正文来自截图转写</span>}
          <span className="jobs-hint">手机上刷到岗位就截图：识别结果先回填到下面，你核对修改后才会存进收件箱。</span>
        </div>
        {guess && <div className="jobs-guess">
          <p className="jobs-hint">
            已识别：{[guess.fields.title, guess.fields.company, guess.fields.city, guess.fields.salary_text]
              .filter(Boolean).join(' · ') || '没有足够信息，下面手动填'}
          </p>
          {guess.duplicate && <p className="jobs-hint jobs-guess-dup">
            这份已在收件箱（{guess.duplicate.title || '未命名'}），保存会更新内容而不是新增
          </p>}
          {guess.fields.warnings.map((warning, index) => <p className="jobs-hint" key={`guess-warning-${index}`}>
            {warning}
          </p>)}
        </div>}
        <div className="jobs-form-grid">
          <label>岗位名称
            <input value={form.title} disabled={disabled} placeholder="留空则由模型解析"
              onChange={event => setForm(previous => ({ ...previous, title: event.target.value }))} />
          </label>
          <label>公司
            <input value={form.company} disabled={disabled} placeholder="选填"
              onChange={event => setForm(previous => ({ ...previous, company: event.target.value }))} />
          </label>
          <label>城市
            <input value={form.city} disabled={disabled} placeholder="选填，如 上海"
              onChange={event => setForm(previous => ({ ...previous, city: event.target.value }))} />
          </label>
          <label>薪资
            <input value={form.salary} disabled={disabled} placeholder="选填，如 25-40K·14薪"
              onChange={event => setForm(previous => ({ ...previous, salary: event.target.value }))} />
          </label>
        </div>
        <label>来源链接
          <input value={form.url} disabled={disabled} placeholder="选填；只记录链接，不抓取页面"
            onChange={event => setForm(previous => ({ ...previous, url: event.target.value }))} />
        </label>
        <label className="jobs-checkbox">
          <input type="checkbox" checked={form.parse} disabled={disabled}
            onChange={event => setForm(previous => ({ ...previous, parse: event.target.checked }))} />
          让模型解析岗位信息（会消耗一次模型调用）
        </label>
        <div className="jobs-actions">
          <button type="button" className="primary-button" disabled={disabled || saving} onClick={submit}>
            {saving ? '保存中…' : '保存到收件箱'}
          </button>
        </div>
      </div>}

      {canManage && showSources && <div className="jobs-form jobs-sources">
        <p className="jobs-hint">
          先选省份，一键启用该省人社厅的招聘公告源。标「未验证」的省份当前抓不到（WAF、页面需前端渲染或域名不可达），
          需要把地址换成该站可直连的「招聘公告」栏目页。
        </p>
        <div className="jobs-form-grid">
          <label>省份
            <select value={provinceCode} disabled={disabled || Boolean(sourceBusy)}
              onChange={event => {
                setProvinceCode(event.target.value)
                setProvinceUrl('')
              }}>
              <option value="">选择省份</option>
              {provinces.map(province => <option key={province.code} value={province.code}>
                {province.name}
                {province.enabled ? '（已启用）' : province.verified ? '' : '（未验证）'}
              </option>)}
            </select>
          </label>
          <label>地址（可覆盖模板）
            <input value={provinceUrl} disabled={disabled || !provinceCode}
              placeholder={selectedProvince?.current_url || selectedProvince?.url || '该省需填写栏目页地址'}
              onChange={event => setProvinceUrl(event.target.value)} />
          </label>
        </div>
        {selectedProvince && <p className="jobs-hint">
          当前状态：{selectedProvince.enabled ? '已启用' : '未启用'}
          {selectedProvince.last_status ? ` · ${selectedProvince.last_status}` : ''}
          {selectedProvince.verified ? '' : ` · ${selectedProvince.note ?? '未验证'}`}
        </p>}
        <div className="jobs-actions">
          <button type="button" className="primary-button" disabled={disabled || !provinceCode || Boolean(sourceBusy)} onClick={() => void toggleProvince()}>
            {sourceBusy === `province-${provinceCode}` ? '处理中…'
              : selectedProvince?.enabled ? '停用该省信源' : '启用该省信源'}
          </button>
          <button type="button" className="secondary-button" disabled={disabled || Boolean(sourceBusy)}
            onClick={() => void fetchAll()}>
            {sourceBusy === 'all' ? '批量抓取中…' : '一键全抓已启用的源'}
          </button>
        </div>
        <p className="jobs-hint">下面是手工录入，也是 BOSS 直聘/智联这类平台的唯一合法入口：把岗位详情复制成文本粘进来。
          我们不抓取这些平台页面，只把你自己看到的内容存进收件箱。</p>
        <div className="jobs-form-grid">
          <label>标识
            <input value={sourceForm.id} disabled={disabled} placeholder="如 gov-hr-js"
              onChange={event => setSourceForm(previous => ({ ...previous, id: event.target.value }))} />
          </label>
          <label>名称
            <input value={sourceForm.name} disabled={disabled} placeholder="如 江苏省人社厅公告"
              onChange={event => setSourceForm(previous => ({ ...previous, name: event.target.value }))} />
          </label>
          <label>类型
            <select value={sourceForm.kind} disabled={disabled}
              onChange={event => setSourceForm(previous => ({ ...previous, kind: event.target.value as 'rss' | 'html_list' }))}>
              <option value="html_list">公告列表页</option>
              <option value="rss">RSS / Atom</option>
            </select>
          </label>
          <label>层级（1 官方一手 ~ 3 媒体）
            <input value={sourceForm.tier} disabled={disabled}
              onChange={event => setSourceForm(previous => ({ ...previous, tier: event.target.value }))} />
          </label>
        </div>
        <label>列表页 / Feed 地址
          <input value={sourceForm.url} disabled={disabled} placeholder="https://…"
            onChange={event => setSourceForm(previous => ({ ...previous, url: event.target.value }))} />
        </label>
        <label>来源说明
          <input value={sourceForm.license_note} disabled={disabled} placeholder="如 政府公开信息"
            onChange={event => setSourceForm(previous => ({ ...previous, license_note: event.target.value }))} />
        </label>
        <label>抓取配置（JSON）
          <textarea rows={4} value={sourceForm.config} disabled={disabled}
            onChange={event => setSourceForm(previous => ({ ...previous, config: event.target.value }))} />
        </label>
        <div className="jobs-actions">
          <button type="button" className="primary-button" disabled={disabled || Boolean(sourceBusy)}
            onClick={() => void saveSource()}>
            {sourceBusy === 'save' ? '保存中…' : '保存信源'}
          </button>
        </div>
        {sources.length > 0 && <ul className="jobs-source-list">
          {sources.map(source => <li key={source.id}>
            <div className="jobs-source-name">
              <strong>{source.name}</strong>
              <span>{source.kind} · tier {source.tier}</span>
            </div>
            <div className="jobs-source-actions">
              <code title={source.last_status}>{source.last_status || '未抓取'}</code>
              <button type="button" className="secondary-button" disabled={disabled || Boolean(sourceBusy)}
                onClick={() => void fetchSource(source.id)}>
                {sourceBusy === source.id ? '抓取中…' : '试抓'}
              </button>
            </div>
          </li>)}
        </ul>}
      </div>}

      <div className="jobs-search">
        <input value={query} disabled={disabled} placeholder="搜索标题、公司、正文"
          onChange={event => setQuery(event.target.value)}
          onKeyDown={event => { if (event.key === 'Enter') void refresh(query) }} />
        <button type="button" className="secondary-button" disabled={disabled || loading}
          onClick={() => void refresh(query)}>搜索</button>
      </div>
      <div className="jobs-stage-filter">
        <label>投递状态筛选
          <select value={stageFilter} disabled={disabled}
            onChange={event => setStageFilter(event.target.value as '' | ApplicationStage)}>
            <option value="">全部</option>
            <option value="saved">已收藏</option>
            <option value="tailored">已定制简历</option>
            <option value="applied">已投递</option>
            <option value="interview">面试中</option>
            <option value="offer">拿到 offer</option>
            <option value="rejected">被拒</option>
            <option value="archived">已归档</option>
          </select>
        </label>
        <span className="jobs-hint">
          进行中 {Object.values(applications).filter(item => item.stage !== 'archived').length} 个岗位
        </span>
      </div>

      {error && <p className="jobs-message jobs-message-error">{error}</p>}
      {notice && !error && <p className="jobs-message">{notice}</p>}

      {loading ? <p className="jobs-empty">正在读取…</p>
        : items.length === 0 ? <p className="jobs-empty">
          {query.trim() ? '没有匹配的资料。' : '收件箱还是空的。点右上角「录入岗位 / 资料」，粘贴 JD 或从截图导入就能开始。'}
        </p>
        : <ul className="jobs-list">
          {items
            .filter(item => !stageFilter || applications[item.id]?.stage === stageFilter)
            .map(item => <li key={item.id}>
            <button type="button" className={`jobs-card ${selected?.id === item.id ? 'active' : ''}`}
              onClick={() => void openDocument(item.id)}>
              <span className="jobs-card-title">{item.title || '未命名资料'}</span>
              <span className="jobs-card-meta">{subtitle(item)}</span>
              <span className="jobs-card-foot">
                {applications[item.id] && <em className="jobs-stage" data-stage={applications[item.id].stage}>
                  {applications[item.id].stage_label}
                </em>}
                {salaryLine(item) || item.kind}
                {item.matched_excerpt && <em>命中：{item.matched_excerpt.slice(0, 24)}…</em>}
              </span>
            </button>
          </li>)}
          {items.filter(item => !stageFilter || applications[item.id]?.stage === stageFilter).length === 0
            && <li className="jobs-empty">这个状态下还没有岗位。在右侧详情里把岗位加入投递看板并推进状态。</li>}
        </ul>}
    </section>

    <section className="panel jobs-detail-panel" aria-labelledby="jobs-detail-title">
      {!selected ? <p className="jobs-empty">左边选一条资料，这里显示解析结果和正文。</p> : <>
        <div className="panel-heading">
          <h2 id="jobs-detail-title">{selected.title || '未命名资料'}</h2>
          <div className="jobs-actions">
            <button type="button" className="secondary-button" disabled={disabled}
              onClick={() => onUseJd(selected.content_md, selected.title)}>用这份 JD 去匹配</button>
            <button type="button" className="secondary-button danger" disabled={disabled}
              onClick={() => void remove(selected.id)}>删除</button>
          </div>
        </div>
        <dl className="jobs-facts">
          <div><dt>公司</dt><dd>{selected.company || '—'}</dd></div>
          <div><dt>城市</dt><dd>{selected.city || '—'}</dd></div>
          <div><dt>薪资</dt><dd>{salaryLine(selected) || '—'}</dd></div>
          <div><dt>来源</dt><dd>{SOURCE_LABELS[selected.source] || selected.source || '—'}</dd></div>
          <div><dt>分块</dt><dd>{chunkCount} 段已建索引</dd></div>
        </dl>
        {selected.url && <p className="jobs-source">来源：
          <a href={selected.url} target="_blank" rel="noreferrer noopener">{selected.url}</a></p>}

        <section className="jobs-application" aria-label="投递状态">
          <div className="jobs-application-head">
            <h3>投递状态</h3>
            <span className="jobs-stage" data-stage={application?.stage || ''}>
              {application ? application.stage_label : '还没加入投递看板'}
            </span>
          </div>
          <div className="jobs-form-grid">
            <label>备注
              <input value={appNote} disabled={disabled} placeholder="如 已投内推、等 HR 回复"
                onChange={event => setAppNote(event.target.value)} />
            </label>
            <label>下一次动作（YYYY-MM-DD）
              <input value={appDate} disabled={disabled} placeholder="如 2026-12-01"
                onChange={event => setAppDate(event.target.value)} />
            </label>
          </div>
          <div className="jobs-actions">
            {!application && <button type="button" className="primary-button" disabled={disabled || busyStage === 'saved'}
              onClick={() => void advanceApplication('saved')}>
              {busyStage === 'saved' ? '保存中…' : '加入投递看板'}
            </button>}
            {application?.next_stage.map(stage => <button key={stage} type="button"
              className="secondary-button" disabled={disabled || Boolean(busyStage)}
              onClick={() => void advanceApplication(stage)}>
              {busyStage === stage ? '保存中…' : `标记为${APPLICATION_STAGE_LABEL[stage]}`}
            </button>)}
            {application && <button type="button" className="secondary-button danger" disabled={disabled}
              onClick={() => void removeApplication()}>移出看板</button>}
          </div>
          {application?.next_action_date && <p className="jobs-hint">下一次动作：{application.next_action_date}</p>}
          {application && application.history && application.history.length > 0 && <details className="jobs-application-history">
            <summary>状态留痕（{application.history.length} 条）</summary>
            <ul>
              {application.history.map((event, index) => <li key={`${event.to_stage}-${index}`}>
                {new Date(event.created_at * 1000).toLocaleString('zh-CN')} ·
                {event.from_stage ? ` ${APPLICATION_STAGE_LABEL[event.from_stage as ApplicationStage]} → ` : ' 新建 · '}
                {APPLICATION_STAGE_LABEL[event.to_stage as ApplicationStage]}
                {event.note ? ` · ${event.note}` : ''}
              </li>)}
            </ul>
          </details>}
        </section>

        {(['hard_requirements', 'soft_requirements', 'responsibilities', 'keywords'] as const).map(key => {
          const values = stringList(selected.structured[key])
          if (!values.length) return null
          const label = { hard_requirements: '硬性要求', soft_requirements: '技能与素质', responsibilities: '岗位职责', keywords: '关键词' }[key]
          return <div className="jobs-section" key={key}>
            <h3>{label}</h3>
            <ul>{values.map((value, index) => <li key={`${key}-${index}`}>{value}</li>)}</ul>
          </div>
        })}

        <div className="jobs-section">
          <h3>正文</h3>
          <pre className="jobs-body">{selected.content_md}</pre>
        </div>
      </>}
    </section>
  </div>
}
