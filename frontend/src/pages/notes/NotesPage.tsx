import { useCallback, useEffect, useState } from 'react'
import { apiErrorMessage, jobsApi } from '../../lib/api'
import type { JobDocument } from '../../lib/api'
import './notes.css'

interface Props {
  userId: string
  disabled: boolean
  /** 从范例库跳到资料库时预选的类型 */
  initialKind?: string
}

const KINDS: Array<{ id: string; label: string; hint: string }> = [
  { id: 'note', label: '笔记', hint: '技术笔记、知识点、待补清单' },
  { id: 'review', label: '面经', hint: '面试复盘：问了什么、怎么答的' },
  { id: 'tech', label: '技术资料', hint: '框架、工具、方案的整理' },
  { id: 'jd', label: 'JD / 岗位', hint: '自己录入的岗位描述' },
]

const untitled = '未命名资料'

/** 私有资料区：笔记 / 面经 / 技术资料 / JD，支持标签、搜索、编辑。 */
export default function NotesPage({ userId, disabled, initialKind = 'note' }: Props) {
  const [kind, setKind] = useState(initialKind)
  const [items, setItems] = useState<JobDocument[]>([])
  const [query, setQuery] = useState('')
  const [tag, setTag] = useState('')
  const [selected, setSelected] = useState<JobDocument | null>(null)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState({ title: '', content_md: '', tags: '' })
  const [form, setForm] = useState({ title: '', text: '', tags: '' })
  const [showForm, setShowForm] = useState(false)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const load = useCallback(async (nextKind: string, keyword: string, nextTag: string) => {
    setLoading(true)
    setError('')
    try {
      const result = await jobsApi.list({
        kind: nextKind || undefined,
        q: keyword.trim() || undefined,
        tag: nextTag.trim() || undefined,
        mine: true,
        limit: 100,
      })
      setItems(result.items)
      setSelected(current => current && result.items.find(item => item.id === current.id) || null)
    } catch (reason) {
      setError(apiErrorMessage(reason))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load(kind, query, tag) }, [load, kind, userId])
  useEffect(() => { setKind(initialKind) }, [initialKind])

  // 标签候选从当前列表里收集，点一下就能筛
  const tags = Array.from(new Set(items.flatMap(item => item.tags || []))).slice(0, 24)

  async function create() {
    if (disabled || busy) return
    if (!form.text.trim()) {
      setError('先写点内容再保存')
      return
    }
    setBusy('create')
    setError('')
    setNotice('')
    try {
      const result = await jobsApi.import({
        text: form.text,
        title: form.title.trim() || undefined,
        kind,
        tags: form.tags.split(/[,，\s]+/).filter(Boolean),
        parse: false,
      })
      setForm({ title: '', text: '', tags: '' })
      setShowForm(false)
      setNotice('已保存到资料库')
      await load(kind, query, tag)
      if (result?.id) {
        const detail = await jobsApi.detail(result.id)
        setSelected(detail.document)
      }
    } catch (reason) {
      setError(apiErrorMessage(reason))
    } finally {
      setBusy('')
    }
  }

  function startEdit(item: JobDocument) {
    setEditing(true)
    setDraft({ title: item.title, content_md: item.content_md, tags: (item.tags || []).join(' ') })
  }

  async function saveEdit() {
    if (!selected || disabled || busy) return
    if (!draft.content_md.trim()) {
      setError('正文不能为空')
      return
    }
    setBusy('edit')
    setError('')
    try {
      const result = await jobsApi.update(selected.id, {
        title: draft.title,
        content_md: draft.content_md,
        tags: draft.tags.split(/[,，\s]+/).filter(Boolean),
      })
      setSelected(result.document)
      setEditing(false)
      setNotice('已保存；正文变了，搜索索引已重建')
      await load(kind, query, tag)
    } catch (reason) {
      setError(apiErrorMessage(reason))
    } finally {
      setBusy('')
    }
  }

  async function remove(id: string) {
    if (disabled || busy) return
    if (!window.confirm('删除这份资料？删除后无法恢复。')) return
    setBusy('remove')
    try {
      await jobsApi.remove(id)
      if (selected?.id === id) setSelected(null)
      setNotice('已删除')
      await load(kind, query, tag)
    } catch (reason) {
      setError(apiErrorMessage(reason))
    } finally {
      setBusy('')
    }
  }

  return <div className="notes-layout">
    <section className="panel notes-list-panel" aria-labelledby="notes-title">
      <div className="panel-heading">
        <h2 id="notes-title">资料库</h2>
        <button type="button" className="secondary-button" disabled={disabled}
          onClick={() => setShowForm(value => !value)}>{showForm ? '收起录入' : '新增资料'}</button>
      </div>
      <nav className="notes-tabs" aria-label="资料类型">
        {KINDS.map(item => <button key={item.id} type="button" aria-pressed={kind === item.id}
          className={kind === item.id ? 'active' : ''} disabled={disabled}
          title={item.hint} onClick={() => setKind(item.id)}>{item.label}</button>)}
      </nav>
      <p className="notes-hint">{KINDS.find(item => item.id === kind)?.hint}</p>

      {showForm && <div className="notes-form">
        <label>标题（选填）
          <input value={form.title} disabled={disabled} placeholder="如 某公司数据岗一面复盘"
            onChange={event => setForm(previous => ({ ...previous, title: event.target.value }))} />
        </label>
        <label>正文
          <textarea rows={6} value={form.text} disabled={disabled}
            placeholder="写清问了什么、你怎么答的、还缺什么；这类内容不会用于生成简历事实。"
            onChange={event => setForm(previous => ({ ...previous, text: event.target.value }))} />
        </label>
        <label>标签（空格或逗号分隔）
          <input value={form.tags} disabled={disabled} placeholder="如 面经 数据岗 SQL"
            onChange={event => setForm(previous => ({ ...previous, tags: event.target.value }))} />
        </label>
        <div className="notes-actions">
          <button type="button" className="primary-button" disabled={disabled || busy === 'create'}
            onClick={() => void create()}>{busy === 'create' ? '保存中…' : '保存到资料库'}</button>
        </div>
      </div>}

      <div className="notes-search">
        <input value={query} disabled={disabled} placeholder="搜索标题与正文"
          onChange={event => setQuery(event.target.value)}
          onKeyDown={event => { if (event.key === 'Enter') void load(kind, query, tag) }} />
        <button type="button" className="secondary-button" disabled={disabled || loading}
          onClick={() => void load(kind, query, tag)}>搜索</button>
      </div>
      {tags.length > 0 && <div className="notes-tagbar">
        <span>标签：</span>
        {tags.map(item => <button key={item} type="button" aria-pressed={tag === item}
          className={tag === item ? 'active' : ''} disabled={disabled}
          onClick={() => { const next = tag === item ? '' : item; setTag(next); void load(kind, query, next) }}>
          {item}
        </button>)}
        {tag && <button type="button" className="notes-tag-clear" disabled={disabled}
          onClick={() => { setTag(''); void load(kind, query, '') }}>清除筛选</button>}
      </div>}

      {error && <p className="notes-message notes-error" role="alert">{error}</p>}
      {notice && !error && <p className="notes-message">{notice}</p>}

      {loading ? <p className="notes-hint">正在读取…</p>
        : items.length === 0 ? <p className="notes-hint">
          这个分类还没有资料。点「新增资料」写一篇，或在上面换个分类看看。
        </p>
        : <ul className="notes-list">
          {items.map(item => <li key={item.id}>
            <button type="button" className={`notes-card ${selected?.id === item.id ? 'active' : ''}`}
              onClick={() => { setSelected(item); setEditing(false) }}>
              <span className="notes-card-title">{item.title || untitled}</span>
              <span className="notes-card-meta">
                {(item.tags || []).length > 0 ? item.tags.join(' · ') : '无标签'}
              </span>
              <span className="notes-card-foot">{new Date(item.updated_at * 1000).toLocaleDateString('zh-CN')}</span>
            </button>
          </li>)}
        </ul>}
    </section>

    <section className="panel notes-detail-panel" aria-labelledby="notes-detail-title">
      {!selected ? <p className="notes-hint">左边选一份资料查看全文；也可以点「新增资料」写一篇。</p>
        : editing ? <>
          <div className="panel-heading"><h2 id="notes-detail-title">编辑资料</h2></div>
          <div className="notes-form">
            <label>标题
              <input value={draft.title} disabled={disabled}
                onChange={event => setDraft(previous => ({ ...previous, title: event.target.value }))} />
            </label>
            <label>正文
              <textarea rows={14} value={draft.content_md} disabled={disabled}
                onChange={event => setDraft(previous => ({ ...previous, content_md: event.target.value }))} />
            </label>
            <label>标签
              <input value={draft.tags} disabled={disabled}
                onChange={event => setDraft(previous => ({ ...previous, tags: event.target.value }))} />
            </label>
            <div className="notes-actions">
              <button type="button" className="primary-button" disabled={disabled || busy === 'edit'}
                onClick={() => void saveEdit()}>{busy === 'edit' ? '保存中…' : '保存修改'}</button>
              <button type="button" className="secondary-button" disabled={disabled}
                onClick={() => setEditing(false)}>取消</button>
            </div>
          </div>
        </> : <>
          <div className="panel-heading">
            <h2 id="notes-detail-title">{selected.title || untitled}</h2>
            <div className="notes-actions">
              <button type="button" className="secondary-button" disabled={disabled}
                onClick={() => startEdit(selected)}>编辑</button>
              <button type="button" className="secondary-button danger" disabled={disabled}
                onClick={() => void remove(selected.id)}>删除</button>
            </div>
          </div>
          <p className="notes-hint">
            {(selected.tags || []).join(' · ') || '无标签'} · 更新于
            {new Date(selected.updated_at * 1000).toLocaleString('zh-CN')}
          </p>
          <pre className="notes-body">{selected.content_md}</pre>
          <p className="notes-hint">
            资料库内容只用于检索与自我提醒，不会被当成简历事实；要写进简历请到工作台确认对应经历。
          </p>
        </>}
    </section>
  </div>
}
