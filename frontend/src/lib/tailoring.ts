import type { ResumeProfile } from './types'

export interface TailoringEvidence {
  id: string; text: string; experience_id: string; experience_name: string; field: string
}
export interface TailoringReport {
  version: 1
  revision_count?: number
  requirements: { id: string; requirement: string; priority: 'core' | 'support'; status: 'supported' | 'gap' | 'omitted'; evidence: TailoringEvidence[]; output_excerpt: string }[]
  selected_experiences: { id: string; name: string }[]
  unsupported_claims: { quote: string; reason: string }[]
  review_note: string
}

export const jdUnits = (jd: string): string[] => [...new Set(jd.split(/[\r\n；;，,。]+/).map((part) => part.trim()).filter(Boolean))]

function hasEvidenceAnchor(quote: string, text: string): boolean {
  if (text.trim().length >= 2 && quote.includes(text.trim()) && !/^[A-Za-z][A-Za-z0-9+#.\-]*$/.test(text.trim())) return true
  for (const token of text.match(/[A-Za-z][A-Za-z0-9+#.\-]*/g) || []) {
    const escaped = token.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    if (token.length >= 2 && new RegExp(`(?<![A-Za-z0-9_])${escaped}(?![A-Za-z0-9_])`, 'i').test(quote)) return true
  }
  return (text.match(/[\u4e00-\u9fff]+/g) || []).some((chunk) => Array.from({ length: Math.max(0, chunk.length - 3) }, (_, i) => chunk.slice(i, i + 4)).some((part) => quote.includes(part)))
}

// 不将旧接口、坏结构或与当前材料不符的依据当作定制成功。
export function tailoringReport(value: unknown, profile: ResumeProfile, jd: string, markdown: string): TailoringReport | null {
  const record = (v: unknown): v is Record<string, any> => !!v && typeof v === 'object' && !Array.isArray(v)
  const nonempty = (v: unknown): v is string => typeof v === 'string' && !!v.trim()
  const units = jdUnits(jd)
  if (!units.length || units.length > 80 || !record(value) || value.version !== 1 || !Array.isArray(value.requirements) || value.requirements.length !== units.length
    || !Array.isArray(value.selected_experiences) || !value.selected_experiences.length || !Array.isArray(value.unsupported_claims) || !nonempty(value.review_note)) return null
  if (value.revision_count !== undefined && value.revision_count !== 0 && value.revision_count !== 1) return null
  const selected = new Set<string>()
  for (const item of value.selected_experiences) {
    if (!record(item) || typeof item.id !== 'string' || !/^e[1-9]\d*$/.test(item.id) || selected.has(item.id)) return null
    const exp = profile.experiences[Number(item.id.slice(1)) - 1]
    if (!exp || item.name !== exp.name) return null
    selected.add(item.id)
  }
  const ids = new Set<string>(), quotes = new Set<string>()
  for (const row of value.requirements) {
    if (!record(row) || !nonempty(row.id) || ids.has(row.id) || !nonempty(row.requirement) || !units.includes(row.requirement) || quotes.has(row.requirement)
      || !['core', 'support'].includes(row.priority) || !['supported', 'gap', 'omitted'].includes(row.status)
      || !Array.isArray(row.evidence) || typeof row.output_excerpt !== 'string'
      || (row.output_excerpt !== '' && (!nonempty(row.output_excerpt) || !markdown.includes(row.output_excerpt)))) return null
    ids.add(row.id); quotes.add(row.requirement)
    const facts = new Set<string>()
    for (const fact of row.evidence) {
      if (!record(fact) || !nonempty(fact.id) || facts.has(fact.id) || !nonempty(fact.text)) return null
      facts.add(fact.id)
      const match = /^(e[1-9]\d*|profile)\.(actions|results|skills|education)\.([1-9]\d*)$/.exec(fact.id)
      if (!match || fact.field !== match[2]) return null
      const [, source, field, index] = match
      const exp = source === 'profile' ? null : profile.experiences[Number(source.slice(1)) - 1]
      if (source !== 'profile' && !exp) return null
      const values = source === 'profile' ? (field === 'skills' || field === 'education' ? profile[field] : [])
        : field === 'education' ? (exp!.kind === 'education' ? [[exp!.name, exp!.role, exp!.period].filter(Boolean).join(' ')] : [])
          : exp![field as 'actions' | 'results' | 'skills']
      if (values[Number(index) - 1] !== fact.text || fact.experience_id !== (exp ? source : '')
        || fact.experience_name !== (exp ? exp.name : '个人资料')) return null
    }
    const active = row.evidence.some((fact: TailoringEvidence) => !fact.experience_id || selected.has(fact.experience_id))
    const status = !row.evidence.length ? 'gap' : active ? 'supported' : 'omitted'
    if (row.status !== status || (status !== 'supported' && row.output_excerpt)) return null
    if (row.output_excerpt && !row.evidence.some((fact: TailoringEvidence) => (!fact.experience_id || selected.has(fact.experience_id)) && hasEvidenceAnchor(row.output_excerpt, fact.text))) return null
  }
  if (!value.unsupported_claims.every((claim: unknown) => record(claim) && nonempty(claim.quote) && markdown.includes(claim.quote) && nonempty(claim.reason))) return null
  return value as unknown as TailoringReport
}
