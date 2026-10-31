import type { Bank, ReportResponse, Session } from './types'

export function bankFixture(count = 12): Bank {
  return { id: 'bank-test', job_title: 'Python 开发', snapshot: { resume_profile: { name: '虚构同学', experiences: [], skills: [], education: [] }, resume_markdown: '# 虚构简历', jd_text: 'Python 开发', captured_at: '2026-10-31T00:00:00Z' },
    sources: [{ id: 's1', kind: 'resume', label: '预约系统', text: '编写接口' }],
    questions: Array.from({ length: count }, (_, i) => ({ id: `topic-${i + 1}`, category: 'experience', question: `为什么选择方案 ${i + 1}？`, focus: '个人贡献', source_ids: ['s1'], follow_ups: ['如何验证？'], answer_structure: ['背景', '行动'], sample_answer: '已确认事实：编写接口。【待补充：实际结果】', missing: ['实际结果'] })),
  }
}
export function sessionFixture(): Session {
  return { id: 'session-test', bank_id: 'bank-test', mode: 'bank', snapshot: bankFixture().snapshot, version: 1, status: 'active', job_title: 'Python 开发', elapsed_seconds: 0, started_at: '2026-10-31',
    turns: [{ id: 'turn-1', question: { text: '请介绍与岗位相关的经历。', stage: 'introduction', topic_id: 'topic-1', is_follow_up: false, suggest_finish: false }, answer: null, skipped: false }] }
}
export function reportFixture(saved = true): ReportResponse {
  return { ok: true, saved, save_error: saved ? null : '报告已生成，历史保存失败', record_id: saved ? 'record-1' : null,
    session: { ...sessionFixture(), status: 'ended' }, report: {
      kind: 'partial', overall_score: null, answered_count: 1, summary: '作答不足，阶段性反馈。', hr_feedback: '动机尚未充分考察。', interviewer_feedback: '建议说明验证过程。',
      dimensions: ['经历陈述与依据', '专业分析', '岗位匹配', '表达结构', '反思与应变'].map((label, i) => ({ key: String(i), label, score: null, comment: '未充分考察。', evidence: [] })),
      strengths: [], improvements: [], optimized_answers: [], recommendations: [{ topic_id: 'topic-1', action: '练习解释个人贡献' }], coverage: [{ topic_id: 'topic-1', focus: '个人贡献', asked: true, answered: true }], disclaimer: '仅用于模拟练习。',
    },
  }
}
