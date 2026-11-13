import { useCallback, useEffect, useState } from 'react'
import { apiErrorMessage, communityApi, jobsApi } from '../../lib/api'
import type { CommunityCard, CommunityComment, CommunityReportGroup, CommunityRevision, CommunityRevisionMeta, CommunitySubmitPayload, JobDocument } from '../../lib/api'
import { diffLines, diffSummary } from '../../lib/textDiff'
import './community.css'

interface Props {
  userId: string
  disabled: boolean
  canManage: boolean
}

type Tab = 'library' | 'submit' | 'review' | 'reports' | 'published'

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

/** 标注清楚每个字段是什么：类型、公司、岗位、轮次各占一格，不混成一行标签。 */
function CardFacts({ card }: { card: CommunityCard }) {
  const facts: Array<[string, string]> = [
    ['类型', KIND_LABEL[card.kind] || card.kind],
    ['公司', card.company || '未填写'],
    ['岗位', card.role || '未填写'],
    ['轮次', card.round || '未填写'],
  ]
  return <dl className="community-facts">
    {facts.map(([label, value]) => <div key={label}>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>)}
  </dl>
}

export default function CommunityPage({ userId, disabled, canManage }: Props) {
  const [tab, setTab] = useState<Tab>('library')
  const [items, setItems] = useState<CommunityCard[]>([])
  const [mine, setMine] = useState<CommunityCard[]>([])
  const [queue, setQueue] = useState<CommunityCard[]>([])
  const [published, setPublished] = useState<CommunityCard[]>([])
  const [reports, setReports] = useState<CommunityReportGroup[]>([])
  const [sla, setSla] = useState<{ open_cards: number; oldest_open_hours: number; over_24h: number
    handled_recent: number; median_handle_hours: number } | null>(null)
  const [commentQueue, setCommentQueue] = useState<CommunityComment[]>([])
  const [comments, setComments] = useState<CommunityComment[]>([])
  const [commentDraft, setCommentDraft] = useState('')
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
  const [docs, setDocs] = useState<JobDocument[]>([])
  // 非空表示正在改这篇投稿；保存后回到待审
  const [editingId, setEditingId] = useState('')
  // 历史版本：展开哪篇投稿、版本列表、选中版本与对比基准
  const [historyId, setHistoryId] = useState('')
  const [historyItems, setHistoryItems] = useState<CommunityRevisionMeta[]>([])
  const [historyVersion, setHistoryVersion] = useState<CommunityRevision | null>(null)
  const [historyCompare, setHistoryCompare] = useState<CommunityRevision | null>(null)

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

  // 引用收件箱里的资料时用下拉选择：用户看不到内部 ID，也不该手输
  const loadDocs = useCallback(async () => {
    try {
      // 只列自己录入的资料：公共岗位池是采集来的公告，拿来当投稿来源全是无关转载
      setDocs((await jobsApi.list({ limit: 50, mine: true })).items)
    } catch {
      setDocs([])
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

  const loadGovernance = useCallback(async () => {
    if (!canManage) return
    try {
      const [reportResult, commentResult, publicResult] = await Promise.all([
        communityApi.reports(),
        communityApi.commentQueue(),
        communityApi.list({ limit: 50 }),
      ])
      setReports(reportResult.items)
      setSla(reportResult.sla)
      setCommentQueue(commentResult.items)
      setPublished(publicResult.items)
    } catch (reason) {
      setError(apiErrorMessage(reason))
    }
  }, [canManage])

  useEffect(() => { void loadLibrary() }, [loadLibrary, userId])
  useEffect(() => { void loadMine() }, [loadMine, userId])
  useEffect(() => { void loadDocs() }, [loadDocs, userId])
  useEffect(() => { void loadQueue() }, [loadQueue, userId])
  useEffect(() => { void loadGovernance() }, [loadGovernance, userId])

  const loadComments = useCallback(async (cardId: string) => {
    try {
      setComments((await communityApi.comments(cardId)).items)
    } catch {
      setComments([])
    }
  }, [])

  useEffect(() => {
    if (selected) void loadComments(selected.id)
    else setComments([])
  }, [selected, loadComments])

  async function submit() {
    if (disabled || busy) return
    if (!form.title.trim()) { setError('请先写清标题，例如「某公司数据岗一面」'); return }
    setBusy('submit')
    setError('')
    setNotice('')
    try {
      const tags = form.tags.split(/[,，\s]+/).filter(Boolean)
      if (editingId) {
        const result = await communityApi.revise(editingId, {
          title: form.title,
          body_md: form.body,
          company: form.company,
          role: form.role,
          round: form.round,
          tags,
        })
        setNotice(result.message || '已保存并重新提交审核')
      } else {
        const payload: CommunitySubmitPayload = {
          kind: form.kind,
          title: form.title,
          body_md: form.body,
          company: form.company,
          role: form.role,
          round: form.round,
          tags,
          ...(form.docId.trim() ? { doc_id: form.docId.trim() } : {}),
        }
        const result = await communityApi.submit(payload)
        setNotice(result.message || '已提交，等待审核')
      }
      setForm(emptyForm)
      setEditingId('')
      await loadMine()
      await loadQueue()
    } catch (reason) {
      setError(apiErrorMessage(reason))
    } finally {
      setBusy('')
    }
  }

  /** 打开/收起某篇投稿的历史版本，默认展示最新一版与它的上一版对比。 */
  async function toggleHistory(card: CommunityCard) {
    if (historyId === card.id) {
      setHistoryId('')
      setHistoryItems([])
      setHistoryVersion(null)
      setHistoryCompare(null)
      return
    }
    setBusy(`history-${card.id}`)
    setError('')
    try {
      const result = await communityApi.revisions(card.id)
      setHistoryId(card.id)
      setHistoryItems(result.items)
      const latest = result.items[0]?.revision ?? 1
      await pickHistoryVersion(card.id, latest, result.items)
    } catch (reason) {
      setError(apiErrorMessage(reason))
    } finally {
      setBusy('')
    }
  }

  /** 选中某一版，并自动取它的上一版做对比（第 1 版没有上一版）。 */
  async function pickHistoryVersion(cardId: string, revision: number,
                                     items: CommunityRevisionMeta[] = historyItems) {
    setBusy(`history-${cardId}`)
    try {
      const current = (await communityApi.revision(cardId, revision)).revision
      setHistoryVersion(current)
      const previous = items.find(item => item.revision === revision - 1)
      setHistoryCompare(previous
        ? (await communityApi.revision(cardId, previous.revision)).revision
        : null)
    } catch (reason) {
      setError(apiErrorMessage(reason))
    } finally {
      setBusy('')
    }
  }

  /** 把这篇投稿装回表单，改完保存会重新进待审。 */
  function startEdit(card: CommunityCard) {
    if (card.status === 'public' && !window.confirm(
      '这是已发布内容，修改后会先从列表撤下并重新进入审核，通过后再公开。继续？')) {
      return
    }
    setEditingId(card.id)
    setForm({
      kind: card.kind,
      title: card.title,
      body: card.body_md,
      company: card.company,
      role: card.role,
      round: card.round,
      tags: card.tags.join(' '),
      docId: '',
    })
    setTab('submit')
    setError('')
    setNotice('已载入这篇投稿，修改后点「保存修改并重新提交」')
  }

  function cancelEdit() {
    setEditingId('')
    setForm(emptyForm)
    setNotice('已取消修改')
  }

  async function resubmit(id: string) {
    if (disabled || busy) return
    if (!window.confirm('内容没改，直接重新提交审核？')) return
    setBusy(`resubmit-${id}`)
    try {
      const result = await communityApi.resubmit(id)
      setNotice(result.message || '已重新提交审核')
      await Promise.all([loadMine(), loadQueue()])
    } catch (reason) {
      setError(apiErrorMessage(reason))
    } finally {
      setBusy('')
    }
  }

  async function toggleHelpful(id: string) {
    if (disabled || busy) return
    try {
      const result = await communityApi.helpful(id)
      setNotice(result.helpful
        ? `已标记有帮助（${result.helpful_count} 人）`
        : `已撤回有帮助（${result.helpful_count} 人）`)
      setItems(previous => previous.map(item => item.id === id
        ? { ...item, viewer_helpful: result.helpful, helpful_count: result.helpful_count }
        : item))
      setSelected(current => current && current.id === id
        ? { ...current, viewer_helpful: result.helpful, helpful_count: result.helpful_count }
        : current)
    } catch (reason) {
      setError(apiErrorMessage(reason))
    }
  }

  async function report(id: string) {
    if (disabled || busy) return
    const reason = window.prompt('举报原因（会同时提交给管理员）', '内容包含联系方式或广告')
    if (!reason || !reason.trim()) return
    try {
      const result = await communityApi.report(id, reason.trim())
      setNotice(result.message)
      await loadLibrary()
      await loadGovernance()
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
      if (selected?.id === id) setSelected(null)
      await Promise.all([loadMine(), loadLibrary(), loadQueue(), loadGovernance()])
    } catch (reason) {
      setError(apiErrorMessage(reason))
    }
  }

  async function review(id: string, action: 'approve' | 'reject' | 'unpublish') {
    if (disabled || busy || !canManage) return
    const note = (rejectNote[id] || '').trim()
    if (action === 'reject' && !note) {
      setError('退回必须写明原因，作者才知道哪里要改')
      return
    }
    if (action === 'unpublish' && !window.confirm('下架后从公开列表撤下，作者会看到下架原因。继续？')) return
    setBusy(id)
    setError('')
    try {
      await communityApi.reviewCard(id, action, note)
      setNotice(action === 'approve' ? '已通过并匿名发布'
        : action === 'reject' ? '已退回，作者能看到原因' : '已下架，作者能看到原因')
      setRejectNote(previous => ({ ...previous, [id]: '' }))
      await Promise.all([loadQueue(), loadMine(), loadLibrary(), loadGovernance()])
    } catch (reason) {
      setError(apiErrorMessage(reason))
    } finally {
      setBusy('')
    }
  }

  async function resolveReports(cardId: string) {
    if (disabled || busy) return
    if (!window.confirm('标记为已处理（内容保留）？')) return
    setBusy(`report-${cardId}`)
    try {
      await communityApi.resolveReports(cardId, '人工核对后保留')
      setNotice('已标记为处理完成，内容保留')
      await Promise.all([loadGovernance(), loadLibrary()])
    } catch (reason) {
      setError(apiErrorMessage(reason))
    } finally {
      setBusy('')
    }
  }

  async function addComment() {
    if (!selected || disabled || busy || !commentDraft.trim()) return
    setBusy('comment')
    setError('')
    try {
      await communityApi.addComment(selected.id, commentDraft.trim())
      setCommentDraft('')
      await loadComments(selected.id)
      setItems(previous => previous.map(item => item.id === selected.id
        ? { ...item, comment_count: item.comment_count + 1 }
        : item))
    } catch (reason) {
      setError(apiErrorMessage(reason))
    } finally {
      setBusy('')
    }
  }

  async function removeComment(id: string) {
    if (disabled || busy) return
    if (!window.confirm('删除这条评论？')) return
    try {
      await communityApi.removeComment(id)
      if (selected) await loadComments(selected.id)
    } catch (reason) {
      setError(apiErrorMessage(reason))
    }
  }

  async function reportComment(id: string) {
    if (disabled || busy) return
    const reason = window.prompt('举报这条评论的原因', '包含广告或联系方式')
    if (!reason || !reason.trim()) return
    try {
      const result = await communityApi.reportComment(id, reason.trim())
      setNotice(result.message)
      if (selected) await loadComments(selected.id)
    } catch (reason) {
      setError(apiErrorMessage(reason))
    }
  }

  async function restoreComment(id: string) {
    if (disabled || busy) return
    try {
      await communityApi.restoreComment(id)
      setNotice('已恢复该评论')
      await loadGovernance()
      if (selected) await loadComments(selected.id)
    } catch (reason) {
      setError(apiErrorMessage(reason))
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
          {canManage && <>
            <button type="button" role="tab" aria-selected={tab === 'review'}
              className={tab === 'review' ? 'active' : ''} onClick={() => setTab('review')}>
              待审核{counts.pending ? `（${counts.pending}）` : ''}
            </button>
            <button type="button" role="tab" aria-selected={tab === 'reports'}
              className={tab === 'reports' ? 'active' : ''} onClick={() => setTab('reports')}>
              举报{reports.length ? `（${reports.length}）` : ''}
            </button>
            <button type="button" role="tab" aria-selected={tab === 'published'}
              className={tab === 'published' ? 'active' : ''} onClick={() => setTab('published')}>
              已发布管理
            </button>
          </>}
        </div>
      </div>

      {error && <p className="community-message community-error">{error}</p>}
      {notice && !error && <p className="community-message">{notice}</p>}
      <p className="community-hint">
        所有内容都匿名展示，作者看得到自己的投稿与评论状态；联系方式在入库前会被隐藏。
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
                <span className="community-card-title">
                  <span className="community-kind">{KIND_LABEL[item.kind]}</span>
                  {item.title}
                </span>
                <span className="community-card-meta">
                  {[item.company, item.role, item.round].filter(Boolean).join(' · ') || '公司 / 岗位未填写'}
                </span>
                <span className="community-card-foot">
                  {item.author} · {stamp(item.published_at)} · 有帮助 {item.helpful_count} · 评论 {item.comment_count}
                </span>
              </button>
            </li>)}
          </ul>}
      </>}

      {tab === 'submit' && <>
        <div className="community-form">
          {editingId && <p className="community-note">
            正在修改一篇投稿：保存后会重新进入待审；如果它之前已发布，会先从列表撤下。
          </p>}
          <div className="community-form-grid">
            <label>卡片类型
              <select value={form.kind} disabled={disabled}
                onChange={event => setForm(previous => ({ ...previous, kind: event.target.value as CommunityCard['kind'] }))}>
                <option value="interview">面经（面试问了什么）</option>
                <option value="referral">内推（渠道与要求）</option>
                <option value="jd_review">JD 评价（要求是否合理）</option>
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
              <input value={form.tags} disabled={disabled} placeholder="选填，用空格分隔，如 SQL 数仓 一面"
                onChange={event => setForm(previous => ({ ...previous, tags: event.target.value }))} />
            </label>
            <label>引用收件箱资料（可选）
              <select value={form.docId} disabled={disabled || busy === 'submit'}
                onChange={event => {
                  const id = event.target.value
                  const doc = docs.find(item => item.id === id)
                  setForm(previous => ({
                    ...previous,
                    docId: id,
                    title: doc ? (previous.title || doc.title) : previous.title,
                    company: doc ? (previous.company || doc.company) : previous.company,
                    role: doc ? (previous.role || doc.role) : previous.role,
                  }))
                }}>
                <option value="">不引用，直接写正文</option>
                {docs.map(doc => <option key={doc.id} value={doc.id}>
                  {doc.title || '未命名资料'}{doc.company ? ` · ${doc.company}` : ''}
                </option>)}
              </select>
            </label>
          </div>
          <div className="community-actions">
            <button type="button" className="primary-button" disabled={disabled || busy === 'submit'}
              onClick={() => void submit()}>
              {busy === 'submit' ? '保存中…' : editingId ? '保存修改并重新提交' : '提交审核'}
            </button>
            {editingId && <button type="button" className="secondary-button" disabled={disabled || busy === 'submit'}
              onClick={cancelEdit}>取消修改</button>}
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
                  {KIND_LABEL[item.kind]}
                  {item.company ? ` · 公司 ${item.company}` : ''}
                  {item.role ? ` · 岗位 ${item.role}` : ''}
                  {item.round ? ` · ${item.round}` : ''}
                  {' · '}提交于 {stamp(item.created_at)}
                </p>
                {item.review_note && <p className="community-note">
                  审核说明：{item.review_note}
                  {item.status === 'rejected' ? '（可以点「编辑」改完再提交，或直接「重新提交」）' : ''}
                </p>}
                {historyId === item.id && <div className="community-history">
                  <div className="community-history-list" role="tablist" aria-label="历史版本">
                    {historyItems.map(version => <button key={version.revision} type="button"
                      role="tab" aria-selected={historyVersion?.revision === version.revision}
                      className={historyVersion?.revision === version.revision ? 'active' : ''}
                      disabled={disabled || busy === `history-${item.id}`}
                      onClick={() => void pickHistoryVersion(item.id, version.revision)}>
                      第 {version.revision} 版 · {stamp(version.created_at)}
                    </button>)}
                  </div>
                  {historyVersion && <div className="community-history-body">
                    <p className="community-hint">
                      正在查看第 {historyVersion.revision} 版
                      {historyCompare
                        ? `；下面是相对第 ${historyCompare.revision} 版的变化（绿色为新增，红色为删除）`
                        : '；这是最早的版本，没有上一版可对比'}
                    </p>
                    <p className="community-hint">标题：{historyVersion.title}</p>
                    {historyCompare ? <pre className="community-diff">
                      {diffLines(historyCompare.body_md, historyVersion.body_md).map((line, index) => (
                        <span key={`${historyVersion.revision}-${index}`} className={`diff-${line.type}`}>
                          {line.type === 'add' ? '+ ' : line.type === 'remove' ? '- ' : '  '}
                          {line.text}
                          {String.fromCharCode(10)}
                        </span>
                      ))}
                    </pre> : <pre className="community-body">{historyVersion.body_md}</pre>}
                    {historyCompare && (() => {
                      const summary = diffSummary(diffLines(historyCompare.body_md, historyVersion.body_md))
                      return <p className="community-hint">
                        本次变化：新增 {summary.added} 行，删除 {summary.removed} 行。
                      </p>
                    })()}
                  </div>}
                </div>}
              </div>
              <div className="community-actions">
                <button type="button" className="secondary-button" disabled={disabled || busy === `history-${item.id}`}
                  aria-expanded={historyId === item.id}
                  onClick={() => void toggleHistory(item)}>
                  {item.revision > 1 ? `历史版本（${item.revision}）` : '历史版本'}
                </button>
                <button type="button" className="secondary-button" disabled={disabled}
                  onClick={() => startEdit(item)}>
                  {item.status === 'public' ? '编辑（会重新审核）' : '编辑'}
                </button>
                {item.status === 'rejected' && <button type="button" className="secondary-button"
                  disabled={disabled || busy === `resubmit-${item.id}`}
                  onClick={() => void resubmit(item.id)}>
                  {busy === `resubmit-${item.id}` ? '提交中…' : '重新提交'}
                </button>}
                <button type="button" className="secondary-button danger" disabled={disabled}
                  onClick={() => void withdraw(item.id)}>
                  {item.status === 'public' ? '撤回已发布内容' : '撤回'}
                </button>
              </div>
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
                  {KIND_LABEL[item.kind]}
                  {item.company ? ` · 公司 ${item.company}` : ''}
                  {item.role ? ` · 岗位 ${item.role}` : ''}
                  {item.round ? ` · ${item.round}` : ''}
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

      {tab === 'reports' && canManage && <>
        <p className="community-hint">
          用户举报会出现在这里（不止是计数）。核对后可以「标记已处理」保留内容，或直接删除。
          累计 3 条举报的内容会自动从列表撤下，等这里处理。
        </p>
        {sla && <dl className="community-sla">
          <div><dt>待处理</dt><dd>{sla.open_cards} 篇</dd></div>
          <div><dt>最久等待</dt><dd>{sla.oldest_open_hours} 小时</dd></div>
          <div><dt>超 24 小时</dt><dd>{sla.over_24h} 篇</dd></div>
          <div><dt>近期处理中位耗时</dt><dd>{sla.median_handle_hours} 小时</dd></div>
        </dl>}
        {reports.length === 0 ? <p className="community-hint">没有待处理的举报。</p>
          : <ul className="community-list">
            {reports.map(group => <li key={group.card_id} className="community-review">
              <div>
                <strong>{group.title}</strong>
                <p className="community-hint">
                  {KIND_LABEL[group.kind]}
                  {group.company ? ` · 公司 ${group.company}` : ''}
                  {group.role ? ` · 岗位 ${group.role}` : ''}
                  {group.round ? ` · ${group.round}` : ''}
                  {' · '}当前状态 {STATUS_LABEL[group.card_status]} · 举报 {group.report_count} 条
                </p>
                <ul className="community-reasons">
                  {group.reasons.map((item, index) => <li key={`${group.card_id}-${index}`}>
                    {item.reason} · {stamp(item.created_at)}
                  </li>)}
                </ul>
              </div>
              <div className="community-actions">
                <button type="button" className="primary-button" disabled={disabled || busy === `report-${group.card_id}`}
                  onClick={() => void resolveReports(group.card_id)}>标记已处理</button>
                <button type="button" className="secondary-button danger" disabled={disabled}
                  onClick={() => void withdraw(group.card_id)}>删除内容</button>
              </div>
            </li>)}
          </ul>}
        <h3 className="community-subtitle">被举报的评论</h3>
        {commentQueue.length === 0 ? <p className="community-hint">没有被撤下的评论。</p>
          : <ul className="community-list">
            {commentQueue.map(comment => <li key={comment.id} className="community-review">
              <div>
                <p className="community-hint">{comment.author} · 举报 {comment.report_count} 次</p>
                <pre className="community-body">{comment.body}</pre>
              </div>
              <div className="community-actions">
                <button type="button" className="primary-button" disabled={disabled}
                  onClick={() => void restoreComment(comment.id)}>恢复评论</button>
                <button type="button" className="secondary-button danger" disabled={disabled}
                  onClick={() => void removeComment(comment.id)}>删除评论</button>
              </div>
            </li>)}
          </ul>}
      </>}

      {tab === 'published' && canManage && <>
        <p className="community-hint">
          已公开内容可以下架（从列表撤下、作者收到原因）或直接删除。
        </p>
        {published.length === 0 ? <p className="community-hint">还没有已发布内容。</p>
          : <ul className="community-list">
            {published.map(item => <li key={item.id} className="community-review">
              <div>
                <strong>{item.title}</strong>
                <p className="community-hint">
                  {KIND_LABEL[item.kind]}
                  {item.company ? ` · 公司 ${item.company}` : ''}
                  {item.role ? ` · 岗位 ${item.role}` : ''}
                  {item.round ? ` · ${item.round}` : ''}
                  {' · '}{item.author} · 有帮助 {item.helpful_count} · 评论 {item.comment_count}
                </p>
              </div>
              <div className="community-actions">
                <button type="button" className="secondary-button" disabled={disabled || busy === item.id}
                  onClick={() => void review(item.id, 'unpublish')}>下架</button>
                <button type="button" className="secondary-button danger" disabled={disabled}
                  onClick={() => void withdraw(item.id)}>删除</button>
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
        <p className="community-hint">
          {selected.author} · 发布于 {stamp(selected.published_at)}
          {selected.revision > 1 ? ` · 第 ${selected.revision} 版` : ''}
        </p>
        <CardFacts card={selected} />
        <pre className="community-body">{selected.body_md}</pre>
        {selected.tags.length > 0 && <p className="community-hint">标签：{selected.tags.join(' · ')}</p>}
        <div className="community-actions">
          <button type="button" className={`secondary-button ${selected.viewer_helpful ? 'active' : ''}`}
            disabled={disabled} aria-pressed={selected.viewer_helpful}
            onClick={() => void toggleHelpful(selected.id)}>
            {selected.viewer_helpful ? `已标记有帮助（${selected.helpful_count}）· 点此撤回` : `有帮助（${selected.helpful_count}）`}
          </button>
          <button type="button" className="secondary-button danger" disabled={disabled}
            onClick={() => void report(selected.id)}>举报</button>
        </div>

        <h3 className="community-subtitle">
          评论（{comments.filter(item => !item.outdated).length}）
          {comments.some(item => item.outdated) ? ` · 另有上一版内容的 ${comments.filter(item => item.outdated).length} 条` : ''}
        </h3>
        {selected.revision > 1 && <p className="community-hint">
          这篇内容已修订过 {selected.revision - 1} 次。旧版本的「有帮助」已作废，
          下面的旧评论仍保留，但那是针对上一版内容的反馈。
        </p>}
        {comments.length === 0 ? <p className="community-hint">还没有评论，说两句你关心的问题。</p>
          : <ul className="community-comments">
            {comments.map(comment => <li key={comment.id} className={comment.outdated ? 'outdated' : ''}>
              <div className="community-comment-head">
                <strong>{comment.author}</strong>
                <span>{stamp(comment.created_at)}</span>
                {comment.outdated && <span className="community-badge">
                  第 {comment.revision} 版内容下的评论
                </span>}
                {comment.status !== 'public' && <span className="community-badge" data-status="rejected">已撤下待审</span>}
              </div>
              <p className="community-comment-body">{comment.body}</p>
              <div className="community-comment-actions">
                {comment.mine && <button type="button" className="link-button" disabled={disabled}
                  onClick={() => void removeComment(comment.id)}>删除</button>}
                {comment.can_manage && !comment.mine && <button type="button" className="link-button" disabled={disabled}
                  onClick={() => void removeComment(comment.id)}>管理员删除</button>}
                {!comment.mine && !comment.outdated && <button type="button" className="link-button" disabled={disabled}
                  onClick={() => void reportComment(comment.id)}>举报</button>}
              </div>
            </li>)}
          </ul>}
        <div className="community-comment-form">
          <textarea value={commentDraft} rows={3} disabled={disabled || busy === 'comment'}
            placeholder="补充你了解的情况（手机号/微信会被隐藏）"
            onChange={event => setCommentDraft(event.target.value)} />
          <button type="button" className="secondary-button" disabled={disabled || busy === 'comment' || !commentDraft.trim()}
            onClick={() => void addComment()}>
            {busy === 'comment' ? '发表中…' : '发表评论'}
          </button>
        </div>
      </>}
    </section>
  </div>
}
