import { useCallback, useEffect, useState } from 'react'
import { apiErrorMessage, jobsApi } from '../../lib/api'
import type { JobDocument } from '../../lib/api'
import './examples.css'

interface Props {
  disabled: boolean
  /** 去资料库写自己的笔记 */
  onOpenNotes: () => void
}

type Example = JobDocument & { structured: Record<string, unknown> }

function tagsOf(item: Example, key: 'role_tags' | 'skill_tags'): string[] {
  const value = item.structured?.[key]
  return Array.isArray(value) ? value.map(String).filter(Boolean) : []
}

/**
 * 范式库：只读浏览写法范例。
 *
 * 这些范例是"同岗位怎么写更好"的参考，**不是用户的事实**：页面明确提示不能照抄，
 * 生成简历时也只把它们当句式参考（提示词里禁止照搬事实与数字，且生成后仍走数字校验）。
 */
export default function ExamplesPage({ disabled, onOpenNotes }: Props) {
  const [items, setItems] = useState<Example[]>([])
  const [role, setRole] = useState('')
  const [skill, setSkill] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const result = await jobsApi.list({ kind: 'example', limit: 100 })
      setItems(result.items as Example[])
    } catch (reason) {
      setError(apiErrorMessage(reason))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  const roles = Array.from(new Set(items.flatMap(item => tagsOf(item, 'role_tags')))).sort()
  const skills = Array.from(new Set(items.flatMap(item => tagsOf(item, 'skill_tags')))).sort()
  const visible = items.filter(item => {
    const matchRole = !role || tagsOf(item, 'role_tags').includes(role)
    const matchSkill = !skill || tagsOf(item, 'skill_tags').includes(skill)
    return matchRole && matchSkill
  })

  return <div className="examples-page">
    <section className="panel" aria-labelledby="examples-title">
      <div className="panel-heading">
        <h2 id="examples-title">写法范例</h2>
        <div className="examples-actions">
          <button type="button" className="secondary-button" disabled={disabled || loading}
            onClick={() => void load()}>刷新</button>
          <button type="button" className="secondary-button" disabled={disabled}
            onClick={onOpenNotes}>去写我的笔记</button>
        </div>
      </div>
      <p className="examples-hint">
        这些是"同岗位怎么写更具体"的参考句式，<strong>不是你的事实</strong>：
        公司、数字、项目都不能照抄；生成简历时也只作写法参考，并会被数字校验拦一次。
      </p>

      {error && <p className="examples-message examples-error" role="alert">{error}</p>}

      <div className="examples-filters">
        <label>岗位
          <select value={role} disabled={disabled} onChange={event => setRole(event.target.value)}>
            <option value="">全部岗位</option>
            {roles.map(item => <option key={item} value={item}>{item}</option>)}
          </select>
        </label>
        <label>技能
          <select value={skill} disabled={disabled} onChange={event => setSkill(event.target.value)}>
            <option value="">全部技能</option>
            {skills.map(item => <option key={item} value={item}>{item}</option>)}
          </select>
        </label>
        <span className="examples-hint">
          共 {items.length} 条，当前 {visible.length} 条
        </span>
      </div>

      {loading ? <p className="examples-hint">正在读取范例…</p>
        : visible.length === 0 ? <p className="examples-hint">
          没有匹配的范例。换个岗位或技能筛选，或去写自己的笔记。
        </p>
        : <ul className="examples-list">
          {visible.map(item => <li key={item.id} className="examples-card">
            <header>
              <strong>{item.title || '未命名范例'}</strong>
              <span className="examples-tags">
                {[...tagsOf(item, 'role_tags'), ...tagsOf(item, 'skill_tags')].slice(0, 6).join(' · ')}
              </span>
            </header>
            <dl>
              <div><dt>弱写法</dt><dd>{String(item.structured?.weak || '—')}</dd></div>
              <div><dt>强写法</dt><dd>{String(item.structured?.strong || '—')}</dd></div>
              <div><dt>手法</dt><dd>{String(item.structured?.technique || '—')}</dd></div>
            </dl>
          </li>)}
        </ul>}
    </section>
  </div>
}
