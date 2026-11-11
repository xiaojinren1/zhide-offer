import { useCallback, useEffect, useState } from 'react'
import { apiErrorMessage, communityApi } from '../../lib/api'
import type { CommunityCard, CommunitySubmitPayload } from '../../lib/api'
import './community.css'

interface Props {
  userId: string
  disabled: boolean
  canManage: boolean
}

type Tab = 'library' | 'submit' | 'review'

const KIND_LABEL: Record<CommunityCard['kind'], string> = {
  interview: '面经',
  referral: '内推',
  jd_review: 'JD 评价',
}

const STATUS_LABEL: Record<CommunityCard['status'], string> = {
  pending: '待审核',
  public: '已发布',
  rejected: '已退回',
}

const emptyForm = {
  kind: 'interview' as CommunityCard['kind'],
  title: '',
  body: '',
  company: '',
  role: '',
  round: '',
  tags: '',
  docId: '',
}

function stamp(value: number | null): string {
  if (!value) return ''
  return new Date(value * 1000).toLocaleDateString('zh-CN')
}

function CardBody({ card }: { card: CommunityCard }) {
  return <>
    <div className="community-facts">
      {card.company && <span>{card.company}</span>}
      {card.role && <span>{card.role}</span>}
      {card.round && <span>{card.round}</span>}
      <span>{KIND_LABEL[card.kind] || card.kind}</span>
    </div>
    <pre className="community-body">{card.body_md}</pre>
    {card.tags.length > 0 && <p className="community-hint">标签：{card.tags.join(' · ')}</p>}
  </>
}

export default function CommunityPage({ userId, disabled, canManage }: Props) {
  const [tab, setTab] = useState<Tab>('library')
  const [items, setItems] = useState<CommunityCard[]>([])
  const [mine, setMine] = useState<CommunityCard[]>([])
  const [queue, setQueue] = useState<CommunityCard[]>([])
  const [counts, setCounts] = useState<Record<string, number>>({})
  const [selected, setSelected] = useState<CommunityCard | null>(null)
  const [kindFilter, setKindFilter] = useState('')
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [form, setForm] = useState(emptyForm)
  const [rejectNote, setRejectNote] = useState<Record<string, string>>({})
  const [reportReason, setReportReason] = useState('')

  const loadLibrary = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const result = await communityApi.list({
        kind: kindFilter || undefined,
        q: query.trim() || undefined,
      })
      setItems(result.items)
      setSelected(current => current && result.items.find(item => item.id === current.id) || null)
    } catch (reason) {
      setError(apiErrorMessage(reason))
    } finally {
      setLoading(false)
    }
  }, [kindFilter, query])

  const loadMine = useCallback(async () => {
    try {
      setMine((await communityApi.mine()).items)
    } catch (reason) {
      setError(apiErrorMessage(reason))
    }
  }, [])

  const loadQueue = useCallback(async () => {
    if (!canManage) return
    try {
      const result = await communityApi.reviewQueue({ status: 'pending' })
      setQueue(result.items)
      setCounts(result.counts)
    } catch (reason) {
      setError(apiErrorMessage(reason))
    }
  }, [canManage])

  useEffect(() => { void loadLibrary() }, [loadLibrary, userId])
  useEffect(() => { void loadMine() }, [loadMine, userId])
  useEffect(() => { void loadQueue() }, [loadQueue, userId])

  async function submit() {
    if (disabled || busy) return
    if (!form.title.trim()) { setError('请先写清标题，例如「某公司数据岗一面」'); return }
    setBusy('submit')
    setError('')
    setNotice('')
    try {
      const payload: CommunitySubmitPayload = {
        kind: form.kind,
        title: form.title,
        body_md: form.body,
        company: form.company,
        role: form.role,
        round: form.round,
        tags: form.tags.split(/[,，\s]+/).filter(Boolean),
        ...(form.docId.trim() ? { doc_id: form.docId.trim() } : {}),
      }
      const result = await communityApi.submit(payload)
      setNotice(result.message || '已提交，等待审核')
      setForm(emptyForm)
      await loadMine()
      await loadQueue()
    } catch (reason) {
      setError(apiErrorMessage(reason))
    } finally {
      setBusy('')
    }
  }

  async function helpful(id: string) {
    if (disabled || busy) return
    try {
      const result = await communityApi.helpful(id)
      setNotice(result.already ? `你已经点过有帮助（${result.helpful_count} 人）` : `已标记有帮助（${result.helpful_count} 人）`)
      await loadLibrary()
    } catch (reason) {
      setError(apiErrorMessage(reason))
    }
  }

  async function report(id: string) {
    if (disabled || busy) return
    const reason = window.prompt('举报原因（会同时提交给管理员）', reportReason || '内容包含联系方式或广告')
    if (!reason || !reason.trim()) return
    setReportReason(reason)
    try {
      const result = await communityApi.report(id, reason.trim())
      setNotice(result.message)
      await loadLibrary()
    } catch (reason) {
      setError(apiErrorMessage(reason))
    }
  }

  async function withdraw(id: string) {
    if (disabled || busy) return
    if (!window.confirm('撤回后这条内容会被删除，确定吗？')) return
    try {
      await communityApi.remove(id)
      setNotice('已撤回')
      await loadMine()
      await loadLibrary()
      await loadQueue()
    } catch (reason) {
      setError(apiErrorMessage(reason))
    }
  }

  async function review(id: string, action: 'approve' | 'reject') {
    if (disabled || busy || !canManage) return
    const note = (rejectNote[id] || '').trim()
    if (action === 'reject' && !note) {
      setError('退回必须写明原因，作者才知道哪里要改')
      return
    }
    setBusy(id)
    setError('')
    try {
      await communityApi.reviewCard(id, action, note)
      setNotice(action === 'approve' ? '已通过并匿名发布' : '已退回，作者能看到原因')
      setRejectNote(previous => ({ ...previous, [id]: '' }))
      await loadQueue()
      await loadMine()
      await loadLibrary()
    } catch (reason) {
      setError(apiErrorMessage(reason))
    } finally {
      setBusy('')
    }
  }

  return <div className="community-layout">
    <section className="panel community-main" aria-labelledby="community-title">
      <div className="panel-heading">
        <h2 id="community-title">面经与内推</h2>
        <div className="community-tabs" role="tablist" aria-label="社群分区">
          <button type="button" role="tab" aria-selected={tab === 'library'}
            className={tab === 'library' ? 'active' : ''} onClick={() => setTab('library')}>面经库</button>
          <button type="button" role="tab" aria-selected={tab === 'submit'}
            className={tab === 'submit' ? 'active' : ''} onClick={() => setTab('submit')}>投稿 / 我的</button>
          {canManage && <button type="button" role="tab" aria-selected={tab === 'review'}
            className={tab === 'review' ? 'active' : ''} onClick={() => setTab('review')}>
            审核{counts.pending ? `（${counts.pending}）` : ''}
          </button>}
        </div>
      </div>

      {error && <p className="community-message community-error">{error}</p>}
      {notice && !error && <p className="community-message">{notice}</p>}
      <p className="community-hint">
        所有内容都匿名展示，作者看得到自己的投稿状态；联系方式在入库前会被隐藏。
        内容仅供求职准备参考，不能替代对公司的实际判断。
      </p>

      {tab === 'library' && <>
        <div className="community-filters">
          <select value={kindFilter} disabled={disabled} aria-label="按类型筛选"
            onChange={event => setKindFilter(event.target.value)}>
            <option value="">全部类型</option>
            <option value="interview">面经</option>
            <option value="referral">内推</option>
            <option value="jd_review">JD 评价</option>
          </select>
          <input value={query} disabled={disabled} placeholder="搜公司、岗位、正文"
            onChange={event => setQuery(event.target.value)}
            onKeyDown={event => { if (event.key === 'Enter') void loadLibrary() }} />
          <button type="button" className="secondary-button" disabled={disabled || loading}
            onClick={() => void loadLibrary()}>搜索</button>
        </div>
        {loading ? <p className="community-hint">正在读取…</p>
          : items.length === 0 ? <p className="community-hint">
            还没有通过审核的内容。审核通过的面经、内推和 JD 评价会出现在这里。
          </p>
          : <ul className="community-list">
            {items.map(item => <li key={item.id}>
              <button type="button" className={`community-card ${selected?.id === item.id ? 'active' : ''}`}
                onClick={() => setSelected(item)}>
                <span className="community-card-title">{item.title}</span>
                <span className="community-card-meta">
                  {[item.company, item.role, item.round].filter(Boolean).join(' · ') || KIND_LABEL[item.kind]}
                </span>
                <span className="community-card-foot">
                  {item.author} · {stamp(item.published_at)} · 有帮助 {item.helpful_count}
                </span>
              </button>
            </li>)}
          </ul>}
      </>}

      {tab === 'submit' && <>
        <div className="community-form">
          <div className="community-form-grid">
            <label>类型
              <select value={form.kind} disabled={disabled}
                onChange={event => setForm(previous => ({ ...previous, kind: event.target.value as CommunityCard['kind'] }))}>
                <option value="interview">面经</option>
                <option value="referral">内推</option>
                <option value="jd_review">JD 评价</option>
              </select>
            </label>
            <label>公司
              <input value={form.company} disabled={disabled} placeholder="选填，如 某科技"
                onChange={event => setForm(previous => ({ ...previous, company: event.target.value }))} />
            </label>
            <label>岗位
              <input value={form.role} disabled={disabled} placeholder="选填，如 数据开发"
                onChange={event => setForm(previous => ({ ...previous, role: event.target.value }))} />
            </label>
            <label>轮次
              <input value={form.round} disabled={disabled} placeholder="选填，如 一面 / HR 面"
                onChange={event => setForm(previous => ({ ...previous, round: event.target.value }))} />
            </label>
          </div>
          <label>标题
            <input value={form.title} disabled={disabled} placeholder="如：某公司数据岗一面，问了数仓分层"
              onChange={event => setForm(previous => ({ ...previous, title: event.target.value }))} />
          </label>
          <label>正文
            <textarea value={form.body} rows={9} disabled={disabled}
              placeholder="写清问了什么、你怎么答的、哪里被追问。手机号和邮箱会在提交时自动隐藏。"
              onChange={event => setForm(previous => ({ ...previous, body: event.target.value }))} />
          </label>
          <div className="community-form-grid">
            <label>标签
              <input value={form.tags} disabled={disabled} placeholder="选填，如 SQL 数仓 一面"
                onChange={event => setForm(previous => ({ ...previous, tags: event.target.value }))} />
            </label>
            <label>从收件箱带入（可选）
              <input value={form.docId} disabled={disabled} placeholder="岗位资料 ID，留空则手写"
                onChange={event => setForm(previous => ({ ...previous, docId: event.target.value }))} />
            </label>
          </div>
          <div className="community-actions">
            <button type="button" className="primary-button" disabled={disabled || busy === 'submit'}
              onClick={() => void submit()}>
              {busy === 'submit' ? '提交中…' : '提交审核'}
            </button>
          </div>
        </div>

        <h3 className="community-subtitle">我的投稿</h3>
        {mine.length === 0 ? <p className="community-hint">还没有投稿记录。</p>
          : <ul className="community-list">
            {mine.map(item => <li key={item.id} className="community-mine">
              <div>
                <strong>{item.title}</strong>
                <span className="community-badge" data-status={item.status}>{STATUS_LABEL[item.status]}</span>
                <p className="community-hint">
                  {KIND_LABEL[item.kind]}{item.company ? ` · ${item.company}` : ''} · 提交于 {stamp(item.created_at)}
                </p>
                {item.review_note && <p className="community-note">审核说明：{item.review_note}</p>}
              </div>
              <button type="button" className="secondary-button danger" disabled={disabled}
                onClick={() => void withdraw(item.id)}>撤回</button>
            </li>)}
          </ul>}
      </>}

      {tab === 'review' && canManage && <>
        <p className="community-hint">
          通过后以匿名马甲发布；退回必须写原因，作者能在「我的投稿」看到。
          待审 {counts.pending ?? 0} 条，已发布 {counts.public ?? 0} 条，已退回 {counts.rejected ?? 0} 条。
        </p>
        {queue.length === 0 ? <p className="community-hint">没有待审内容。</p>
          : <ul className="community-list">
            {queue.map(item => <li key={item.id} className="community-review">
              <div>
                <strong>{item.title}</strong>
                <p className="community-hint">
                  {KIND_LABEL[item.kind]}{item.company ? ` · ${item.company}` : ''}
                  {item.role ? ` · ${item.role}` : ''}{item.round ? ` · ${item.round}` : ''}
                  {item.report_count ? ` · 被举报 ${item.report_count} 次` : ''}
                </p>
                {item.review_note && <p className="community-note">{item.review_note}</p>}
                <pre className="community-body">{item.body_md}</pre>
                <input value={rejectNote[item.id] || ''} disabled={disabled}
                  placeholder="退回原因（退回必填）"
                  onChange={event => setRejectNote(previous => ({ ...previous, [item.id]: event.target.value }))} />
              </div>
              <div className="community-actions">
                <button type="button" className="primary-button" disabled={disabled || busy === item.id}
                  onClick={() => void review(item.id, 'approve')}>通过并发布</button>
                <button type="button" className="secondary-button danger" disabled={disabled || busy === item.id}
                  onClick={() => void review(item.id, 'reject')}>退回</button>
              </div>
            </li>)}
          </ul>}
      </>}
    </section>

    <section className="panel community-detail" aria-labelledby="community-detail-title">
      {!selected ? <p className="community-hint">左边选一条面经查看全文；投稿在「投稿 / 我的」里。</p> : <>
        <div className="panel-heading">
          <h2 id="community-detail-title">{selected.title}</h2>
        </div>
        <p className="community-hint">{selected.author} · {stamp(selected.published_at)}</p>
        <CardBody card={selected} />
        <div className="community-actions">
          <button type="button" className="secondary-button" disabled={disabled}
            onClick={() => void helpful(selected.id)}>
            有帮助（{selected.helpful_count}）
          </button>
          <button type="button" className="secondary-button danger" disabled={disabled}
            onClick={() => void report(selected.id)}>举报</button>
        </div>
      </>}
    </section>
  </div>
}
