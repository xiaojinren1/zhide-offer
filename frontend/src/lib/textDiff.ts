/**
 * 极简行级 diff：用于对比投稿的历史版本。
 *
 * 只用 LCS 求最长公共子序列，够看清"这一版加了哪段、删了哪段"，不追求字符级
 * 精细度。两版都按行比较，适合面经这种短文本（几百行以内）。
 */
export type DiffLine = { type: 'same' | 'add' | 'remove'; text: string }

function lcsTable(a: string[], b: string[]): number[][] {
  const table: number[][] = Array.from({ length: a.length + 1 }, () => new Array(b.length + 1).fill(0))
  for (let i = a.length - 1; i >= 0; i -= 1) {
    for (let j = b.length - 1; j >= 0; j -= 1) {
      table[i][j] = a[i] === b[j] ? table[i + 1][j + 1] + 1 : Math.max(table[i + 1][j], table[i][j + 1])
    }
  }
  return table
}

/** 返回从 a（旧版）到 b（新版）的变化；`same` 表示两版相同。 */
export function diffLines(oldText: string, newText: string): DiffLine[] {
  const a = String(oldText || '').split('\n')
  const b = String(newText || '').split('\n')
  const table = lcsTable(a, b)
  const result: DiffLine[] = []
  let i = 0
  let j = 0
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      result.push({ type: 'same', text: a[i] })
      i += 1
      j += 1
    } else if (table[i + 1][j] >= table[i][j + 1]) {
      result.push({ type: 'remove', text: a[i] })
      i += 1
    } else {
      result.push({ type: 'add', text: b[j] })
      j += 1
    }
  }
  while (i < a.length) {
    result.push({ type: 'remove', text: a[i] })
    i += 1
  }
  while (j < b.length) {
    result.push({ type: 'add', text: b[j] })
    j += 1
  }
  return result
}

/** 统计变化行数，用于列表上给一句"改了 N 行"。 */
export function diffSummary(lines: DiffLine[]): { added: number; removed: number } {
  return {
    added: lines.filter(line => line.type === 'add').length,
    removed: lines.filter(line => line.type === 'remove').length,
  }
}
