import type { Experience, ResumeProfile } from './types'
export type Card = Experience & { id: string; deleted: boolean; source_ids: string[]; history: Array<{ at: string; facts: Experience; deleted: boolean; source_ids: string[] }> }
export type Bank = { revision: number; cards: Card[]; sources: Array<{id: string; name: string; at: string; profile: ResumeProfile}>; migrated: string[]; legacy: Array<{id: string; name: string; saved_at: string}> }
export type Material = { expected_user_id: string; profile?: ResumeProfile; legacy_id?: string; source_name: string }
export type Candidate = { id: string; facts: Experience; same: boolean; conflicts?: string[] }
export type Proposal = { incoming: Experience; status: 'same' | 'review' | 'new'; candidates: Candidate[] }
export type Preview = { revision: number; items: Proposal[]; education_notes: string[]; profile: ResumeProfile }
export type Choice = { action: 'skip' | 'new' | 'merge'; target?: string; fields: string[]; replace_fields: string[] }
export const labels: Record<string, string> = { name: '名称', role: '角色 / 专业学历', period: '起止时间', actions: '行动与方法', results: '成果和数据', skills: '技能' }
export const fields = Object.keys(labels) as Array<keyof Experience>
export function assembled(cards: Card[], name: string): ResumeProfile {
  return {name, experiences: cards.map(({kind,name,role,period,actions,results,skills}) => ({kind,name,role,period,actions,results,skills})), education: [], skills: [...new Set(cards.flatMap(c => c.skills))], user_confirmed: false, raw_text: cards.map(c => [c.name,c.role,c.period,...c.actions,...c.results].join('\n')).join('\n\n')}
}
