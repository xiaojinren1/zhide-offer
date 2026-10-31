import type { MatchReport, ResumeProfile } from '../../lib/types'

export function matchInputSnapshot(jdText: string, profile: ResumeProfile | null, markdown: string): string {
  return JSON.stringify([jdText, profile, markdown])
}

export function matchSuggestions(report: MatchReport) {
  return report.items.flatMap((item, index) => {
    if (item.status === 'missing' || !item.evidence.trim()) return []
    return [{
      id: `job-match-${index}`,
      type: 'job_match',
      location: item.requirement,
      detail: `岗位要求：${item.requirement}\n已确认材料中的证据：${item.evidence}`,
      suggestion: item.status === 'partial'
        ? '仅突出已有证据能够支持的部分，保留能力边界；不能把未覆盖要求写成个人事实。'
        : '根据已确认事实调整相关内容的表达或顺序，使已有证据更清楚；不能新增事实。',
      severity: 'medium',
    }]
  })
}

export function chosenMatchSuggestions(report: MatchReport, selected: string[]) {
  const suggestions = matchSuggestions(report).filter(item => selected.includes(item.id))
  if (!suggestions.length) throw new Error('请先选择至少一条有事实依据的建议。')
  if (suggestions.length > 30) throw new Error('每次最多应用 30 条建议，请分批选择。')
  return suggestions
}
