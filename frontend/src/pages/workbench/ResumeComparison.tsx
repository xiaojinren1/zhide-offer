import { useMemo } from 'react'

function changedLines(before: string[], after: string[]) {
  const removed = new Set<number>()
  const added = new Set<number>()
  // Bound memory for large pasted drafts.
  if (before.length * after.length > 250_000) return null
  const lengths = Array.from({ length: before.length + 1 }, () => new Uint32Array(after.length + 1))
  for (let i = before.length - 1; i >= 0; i--) {
    for (let j = after.length - 1; j >= 0; j--) {
      lengths[i][j] = before[i] === after[j] ? 1 + lengths[i + 1][j + 1] : Math.max(lengths[i + 1][j], lengths[i][j + 1])
    }
  }
  let i = 0
  let j = 0
  while (i < before.length && j < after.length) {
    if (before[i] === after[j]) {
      i++
      j++
    } else if (lengths[i + 1][j] >= lengths[i][j + 1]) {
      removed.add(i++)
    } else {
      added.add(j++)
    }
  }
  while (i < before.length) removed.add(i++)
  while (j < after.length) added.add(j++)
  return { removed, added }
}

export default function ResumeComparison({ before, after }: { before: string; after: string }) {
  const { original, revised, changes } = useMemo(() => {
    const original = before.split(/\r\n?|\n/)
    const revised = after.split(/\r\n?|\n/)
    return { original, revised, changes: changedLines(original, revised) }
  }, [before, after])

  return <div className="resume-comparison">
    {!changes && <p>稿件行数较多，以下并排展示全文。</p>}
    {changes && !changes.removed.size && !changes.added.size && <p>本次优化未改变正文。</p>}
    <div className="resume-comparison-columns">
      <section><h4>修改前</h4><pre>{original.map((line, index) => <span key={index} className={changes?.removed.has(index) ? 'resume-removed' : undefined}>{changes?.removed.has(index) && <strong>删除 · </strong>}{line || ' '}</span>)}</pre></section>
      <section><h4>修改后</h4><pre>{revised.map((line, index) => <span key={index} className={changes?.added.has(index) ? 'resume-added' : undefined}>{changes?.added.has(index) && <strong>新增 · </strong>}{line || ' '}</span>)}</pre></section>
    </div>
  </div>
}
