import { useCallback, useEffect, useState } from 'react'
import { apiErrorMessage, jobsApi } from '../../lib/api'
import type { JobDocument } from '../../lib/api'
import './jobs.css'

interface Props {
  userId: string
  disabled: boolean
  onUseJd: (text: string, title: string) => void
}

interface ImportForm {
  text: string
  title: string
  company: string
  city: string
  salary: string
  url: string
  parse: boolean
}

const emptyForm: ImportForm = {
  text: '', title: '', company: '', city: '', salary: '', url: '', parse: true,
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

export default function JobsPage({ userId, disabled, onUseJd }: Props) {
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

  useEffect(() => { void refresh('') }, [refresh, userId])

  async function openDocument(id: string) {
    try {
      const result = await jobsApi.detail(id)
      setSelected(result.document)
      setChunkCount(result.chunks.length)
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
      </div>

      {showForm && <div className="jobs-form">
        <label>岗位 JD 或资料正文
          <textarea value={form.text} rows={8} disabled={disabled}
            placeholder="把 JD 全文粘进来。模型可用时会自动解析岗位名、公司、要求；解析失败也会按原文保存。"
            onChange={event => setForm(previous => ({ ...previous, text: event.target.value }))} />
        </label>
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

      <div className="jobs-search">
        <input value={query} disabled={disabled} placeholder="搜索标题、公司、正文"
          onChange={event => setQuery(event.target.value)}
          onKeyDown={event => { if (event.key === 'Enter') void refresh(query) }} />
        <button type="button" className="secondary-button" disabled={disabled || loading}
          onClick={() => void refresh(query)}>搜索</button>
      </div>

      {error && <p className="jobs-message jobs-message-error">{error}</p>}
      {notice && !error && <p className="jobs-message">{notice}</p>}

      {loading ? <p className="jobs-empty">正在读取…</p>
        : items.length === 0 ? <p className="jobs-empty">
          {query.trim() ? '没有匹配的资料。' : '收件箱还是空的。点右上角「录入岗位 / 资料」，把 JD 粘进来就能开始。'}
        </p>
        : <ul className="jobs-list">
          {items.map(item => <li key={item.id}>
            <button type="button" className={`jobs-card ${selected?.id === item.id ? 'active' : ''}`}
              onClick={() => void openDocument(item.id)}>
              <span className="jobs-card-title">{item.title || '未命名资料'}</span>
              <span className="jobs-card-meta">{subtitle(item)}</span>
              <span className="jobs-card-foot">
                {salaryLine(item) || item.kind}
                {item.matched_excerpt && <em>命中：{item.matched_excerpt.slice(0, 24)}…</em>}
              </span>
            </button>
          </li>)}
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
          <div><dt>分块</dt><dd>{chunkCount} 段已建索引</dd></div>
        </dl>
        {selected.url && <p className="jobs-source">来源：
          <a href={selected.url} target="_blank" rel="noreferrer noopener">{selected.url}</a></p>}

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
