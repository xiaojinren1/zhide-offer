/** 与 backend/engine/models.py 对齐的数据契约 */
export interface Experience {
  kind: string
  name: string
  role: string
  period: string
  actions: string[]
  results: string[]
  skills: string[]
}

export interface ResumeProfile {
  name: string
  experiences: Experience[]
  skills: string[]
  education: string[]
  raw_text?: string
  user_confirmed?: boolean
}

export interface Suspicion {
  type: string
  location: string
  detail: string
  suggestion: string
  severity: 'high' | 'medium' | 'low'
  program_verified: boolean
}

export interface ParsedJD {
  job_title: string
  company: string
  hard_requirements: string[]
  soft_requirements: string[]
  responsibilities: string[]
  keywords: string[]
  evidence: Record<string, string>
  inferred: string[]
}

export interface MatchItem {
  requirement: string
  status: 'covered' | 'partial' | 'missing'
  evidence: string
  note: string
}

export interface MatchReport {
  job_title: string
  coverage: number
  items: MatchItem[]
  missing_hard: string[]
}

export interface QualityReport {
  keyword_coverage: number
  quantified_ratio: number
  cliche_hits: string[]
  ats_issues: string[]
  consistency_issues: string[]
  suspicions: Suspicion[]
  passed: boolean
}
