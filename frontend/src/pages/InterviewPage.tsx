import { useEffect, useMemo, useRef, useState } from 'react'
import { api, apiErrorMessage } from '../lib/api'
import type {
  InterviewQuestion,
  InterviewScore,
  ResumeProfile,
  Suspicion,
} from '../lib/types'
import type { InterviewRecord } from '../lib/workspace'

interface Props {
  userId?: string
  jdText: string
  profile: ResumeProfile | null
  markdown: string
}

interface InterviewStartResponse {
  ok: boolean
  error?: string
  round?: number
  questions?: InterviewQuestion[]
  suspicions?: Suspicion[]
}

type HistoryItem = Pick<InterviewRecord, 'id' | 'title' | 'saved_at'>

function roundKey(round: number, questions: InterviewQuestion[], scores: Record<string, InterviewScore>) {
  return `${round}:${questions.map((question) => `${question.id}:${scores[question.id]?.score ?? ''}`).join('|')}`
}

const categoryLabel: Record<InterviewQuestion['category'], string> = {
  timeline: '时间线',
  skill_authenticity: '技能真实性',
  project_match: '项目成果 / 岗位匹配',
}

function scoreColor(score: number) {
  if (score >= 80) return 'text-emerald-600'
  if (score >= 60) return 'text-amber-600'
  return 'text-red-600'
}

function scoreLabel(score: number) {
  if (score >= 80) return '表现稳定'
  if (score >= 60) return '基本可用'
  return '需要重练'
}

export default function InterviewPage({ userId = '', jdText, profile, markdown }: Props) {
  const [busy, setBusy] = useState(false)
  const [scoringId, setScoringId] = useState('')
  const [error, setError] = useState('')
  const [round, setRound] = useState(1)
  const [questions, setQuestions] = useState<InterviewQuestion[]>([])
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [scores, setScores] = useState<Record<string, InterviewScore>>({})
  const [suspicions, setSuspicions] = useState<Suspicion[]>([])
  const [historyRecords, setHistoryRecords] = useState<HistoryItem[]>([])
  const [historyBusy, setHistoryBusy] = useState(false)
  const [historyError, setHistoryError] = useState('')
  const [saveError, setSaveError] = useState('')
  const [saveRetry, setSaveRetry] = useState(0)
  const savedRoundKey = useRef('')
  const savingRoundKey = useRef('')

  useEffect(() => {
    let active = true
    setHistoryRecords([])
    setHistoryError('')
    if (!userId) return () => { active = false }
    setHistoryBusy(true)
    void api.listInterviewRecords()
      .then((result) => {
        if (active) setHistoryRecords(result.records || [])
      })
      .catch((cause) => {
        if (active) setHistoryError(apiErrorMessage(cause))
      })
      .finally(() => {
        if (active) setHistoryBusy(false)
      })
    return () => { active = false }
  }, [userId])

  const startRound = async () => {
    if (!profile || !markdown.trim()) {
      setError('请先完成事实确认并生成简历，再开始模拟面试。')
      return
    }
    setBusy(true)
    setError('')
    setScores({})
    setAnswers({})
    savedRoundKey.current = ''
    setSaveError('')
    try {
      const response = await api.interview(markdown, profile, jdText) as InterviewStartResponse
      if (!response.ok || !response.questions?.length) {
        setError(response.error || '暂时无法生成面试题，请稍后重试。')
        return
      }
      setQuestions(response.questions.slice(0, 3))
      setSuspicions(response.suspicions || [])
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '暂时无法连接面试服务。')
    } finally {
      setBusy(false)
    }
  }

  const submitAnswer = async (question: InterviewQuestion) => {
    const answer = (answers[question.id] || '').trim()
    if (!answer) {
      setError('请先填写本题回答，再提交评分。')
      return
    }
    setScoringId(question.id)
    setError('')
    try {
      const data = await api.scoreInterview(profile, jdText, question, answer)
      if (!data.ok) {
        setError(data.detail || '本题评分失败，请修改回答后重试。')
        return
      }
      setScores((previous) => ({ ...previous, [question.id]: data }))
    } catch (cause) {
      setError(apiErrorMessage(cause))
    } finally {
      setScoringId('')
    }
  }

  const restartQuestion = (question: InterviewQuestion) => {
    savedRoundKey.current = ''
    setSaveError('')
    setScores((previous) => {
      const next = { ...previous }
      delete next[question.id]
      return next
    })
    setAnswers((previous) => ({ ...previous, [question.id]: '' }))
    setError('')
  }

  const startNextRound = () => {
    setRound((previous) => previous + 1)
    setQuestions([])
    setScores({})
    setAnswers({})
    setSuspicions([])
    setError('')
    setSaveError('')
    savedRoundKey.current = ''
  }

  const completed = questions.length > 0 && questions.every((question) => scores[question.id])
  const summary = useMemo(() => {
    const values = Object.values(scores)
    if (!values.length) return null
    const total = Math.round(values.reduce((sum, item) => sum + item.score, 0) / values.length)
    const issues = Array.from(new Set(values.flatMap((item) => item.issues))).slice(0, 4)
    return { total, issues }
  }, [scores])

  useEffect(() => {
    if (!userId || !completed || !summary || !questions.length) return
    const key = roundKey(round, questions, scores)
    if (savedRoundKey.current === key || savingRoundKey.current === key) return
    savingRoundKey.current = key
    setSaveError('')
    void api.saveInterviewRecord(userId, {
      title: `模拟面试 · 第 ${round} 轮`,
      jd_text: jdText,
      questions: questions as unknown as Record<string, unknown>[],
      answers: questions.map((question) => answers[question.id] || ''),
      question_scores: questions.map((question) => scores[question.id] as unknown as Record<string, unknown>),
      overall_feedback: { total: summary.total, issues: summary.issues },
    }).then((result) => {
      savedRoundKey.current = key
      setHistoryRecords((previous) => [{ id: result.id, title: `模拟面试 · 第 ${round} 轮`, saved_at: result.saved_at }, ...previous.filter((item) => item.id !== result.id)])
    }).catch((cause) => {
      setSaveError(apiErrorMessage(cause))
    }).finally(() => {
      if (savingRoundKey.current === key) savingRoundKey.current = ''
    })
  }, [answers, completed, jdText, questions, round, saveRetry, scores, summary, userId])

  async function loadHistory(id: string) {
    setHistoryBusy(true)
    setHistoryError('')
    try {
      const result = await api.loadInterviewRecord(id)
      const loadedQuestions = (result.record.questions || []) as unknown as InterviewQuestion[]
      const loadedScores = (result.record.question_scores || []) as unknown as InterviewScore[]
      const scoreMap = Object.fromEntries(loadedScores.filter((score) => score.question_id).map((score) => [score.question_id, score]))
      const answerMap = Object.fromEntries(loadedQuestions.map((question, index) => [question.id, result.record.answers?.[index] || '']))
      setRound(1)
      setQuestions(loadedQuestions)
      setAnswers(answerMap)
      setScores(scoreMap)
      setSuspicions([])
      savedRoundKey.current = roundKey(1, loadedQuestions, scoreMap)
      setSaveError('')
      setError('')
    } catch (cause) {
      setHistoryError(apiErrorMessage(cause))
    } finally {
      setHistoryBusy(false)
    }
  }

  async function deleteHistory(id: string) {
    setHistoryBusy(true)
    setHistoryError('')
    try {
      await api.deleteInterviewRecord(id)
      setHistoryRecords((previous) => previous.filter((item) => item.id !== id))
    } catch (cause) {
      setHistoryError(apiErrorMessage(cause))
    } finally {
      setHistoryBusy(false)
    }
  }

  return (
    <div className="space-y-5 interview-page">
      <header className="page-heading" style={{ marginBottom: 0 }}>
        <div>
          <span className="eyebrow">INTERVIEW PRACTICE · ROUND {round}</span>
          <h1>三题模拟面试</h1>
          <p>按真实经历回答，提交后查看事实依据、岗位匹配、表达清晰度和结构完整度。</p>
        </div>
        <span className="heading-badge">文字模拟已就绪 · 语音为加分项</span>
      </header>

      {error && <div className="error-banner" role="alert"><span>{error}</span></div>}
      {historyError && <div className="error-banner" role="alert"><span>{historyError}</span></div>}
      {saveError && <div className="notice" role="alert"><span>本轮已完成，但历史保存失败：{saveError}</span><button className="secondary-button" onClick={() => { setSaveError(''); setSaveRetry((value) => value + 1) }}>重试保存</button></div>}

      {!questions.length && (
        <section className="panel" style={{ maxWidth: 760 }}>
          <div className="panel-heading">
            <div>
              <span className="section-kicker">START A PRACTICE ROUND</span>
              <h2>准备好回答三道追问了吗？</h2>
            </div>
            <span className="tag blue">共 3 题</span>
          </div>
          <p className="panel-description">
            题目固定覆盖时间线、技能真实性、项目成果或岗位匹配。评分由简历和 JD 中可复核的字段计算。
          </p>
          <div className="next-step" style={{ marginTop: 8 }}>
            <div className="next-icon">C</div>
            <div>
              <h3>先用文字完成一轮</h3>
              <p>每题都可以重练；全部提交后会显示总分和下一轮建议。</p>
            </div>
            <button className="primary-button" onClick={() => void startRound()} disabled={busy || !profile || !markdown.trim()}>
              {busy ? '生成题目中…' : round === 1 ? '开始第一轮' : '生成下一轮'}
            </button>
          </div>
          {(!profile || !markdown.trim()) && (
            <p className="button-hint">请先回到工作台完成事实确认并生成简历。</p>
          )}
        </section>
      )}

      {historyRecords.length > 0 && (
        <section className="panel" aria-label="面试历史">
          <div className="panel-heading"><div><span className="section-kicker">PRACTICE HISTORY</span><h2>最近的面试记录</h2></div><span className="tag blue">{historyRecords.length} 轮</span></div>
          <div className="space-y-2">
            {historyRecords.map((record) => (
              <div key={record.id} className="next-step" style={{ marginTop: 8 }}>
                <div><strong>{record.title}</strong><p className="muted">保存于 {record.saved_at}</p></div>
                <div className="memory-actions"><button className="secondary-button" disabled={historyBusy} onClick={() => void loadHistory(record.id)}>恢复</button><button className="memory-danger" disabled={historyBusy} onClick={() => void deleteHistory(record.id)}>删除</button></div>
              </div>
            ))}
          </div>
        </section>
      )}

      {questions.length > 0 && (
        <>
          <div className="activity-banner">
            <strong>第 {round} 轮 · 已完成 {Object.keys(scores).length}/{questions.length} 题</strong>
            <span>回答中可以引用项目名称、时间、个人动作和可核验结果。</span>
          </div>

          <div className="space-y-4">
            {questions.map((question) => {
              const result = scores[question.id]
              const answer = answers[question.id] || ''
              return (
                <article key={question.id} className="panel">
                  <div className="panel-heading">
                    <div>
                      <span className="section-kicker">QUESTION {question.index} · {categoryLabel[question.category]}</span>
                      <h2>{question.question}</h2>
                    </div>
                    {result && <span className={'tag ' + (result.score >= 80 ? 'green' : result.score >= 60 ? 'amber' : 'blue')}>{result.score} 分</span>}
                  </div>
                  <div className="notice" style={{ marginBottom: 14 }}>
                    <strong>评分依据：</strong>{question.evidence}
                    <br />
                    <span className="muted">关注点：{question.focus}</span>
                  </div>
                  <label className="field-label" htmlFor={'answer-' + question.id}>
                    你的回答 <span>{answer.length} 字</span>
                  </label>
                  <textarea
                    id={'answer-' + question.id}
                    value={answer}
                    onChange={(event) => setAnswers((previous) => ({ ...previous, [question.id]: event.target.value }))}
                    placeholder="建议按“背景/目标 → 个人行动 → 结果证据 → 复盘 → 岗位匹配”回答"
                    rows={5}
                    disabled={Boolean(result) || scoringId === question.id}
                  />
                  {!result && (
                    <button className="primary-button" style={{ marginTop: 12, alignSelf: 'flex-start' }} onClick={() => void submitAnswer(question)} disabled={scoringId === question.id}>
                      {scoringId === question.id ? '评分中…' : '提交本题并评分'}
                    </button>
                  )}
                  {result && (
                    <div style={{ marginTop: 16 }}>
                      <div className="stepper" style={{ marginBottom: 14, padding: 12 }}>
                        {(['evidence', 'job_match', 'clarity', 'structure'] as const).map((key) => (
                          <div key={key} style={{ flex: 1, textAlign: 'center' }}>
                            <div className="muted">{({ evidence: '事实依据', job_match: '岗位匹配', clarity: '表达清晰', structure: '结构完整' })[key]}</div>
                            <strong className={scoreColor(result.dimensions[key])}>{result.dimensions[key]}</strong>
                          </div>
                        ))}
                      </div>
                      <p className={'text-sm font-medium ' + scoreColor(result.score)}>{scoreLabel(result.score)}：{result.summary}</p>
                      {result.issues.length > 0 && (
                        <ul className="mt-2 text-sm text-gray-600 list-disc pl-5">
                          {result.issues.map((issue) => <li key={issue}>{issue}</li>)}
                        </ul>
                      )}
                      <div className="notice" style={{ marginTop: 12, marginBottom: 0 }}>
                        <strong>推荐回答结构：</strong>{result.recommended_structure}
                        <br />
                        <strong>改进建议：</strong>{result.improvement}
                      </div>
                      <button className="secondary-button" style={{ marginTop: 12 }} onClick={() => restartQuestion(question)}>
                        重新回答本题
                      </button>
                    </div>
                  )}
                </article>
              )
            })}
          </div>

          {completed && summary && (
            <section className="next-step">
              <div className="next-icon">✓</div>
              <div>
                <h3>本轮总分 {summary.total} · {scoreLabel(summary.total)}</h3>
                <p>{summary.issues.length ? '主要问题：' + summary.issues.join('；') : '三题均已完成，下一轮可以继续压缩表达并加强岗位迁移。'}</p>
              </div>
              <button className="secondary-button" onClick={startNextRound}>开始下一轮</button>
            </section>
          )}

          {suspicions.length > 0 && (
            <details className="panel">
              <summary className="text-sm font-medium cursor-pointer">本轮程序检测到的简历疑点（{suspicions.length} 条）</summary>
              <ul className="mt-2 space-y-1 text-xs text-gray-600 list-disc pl-5">
                {suspicions.map((item) => <li key={item.type + '-' + item.location}>[{item.type}] {item.detail}</li>)}
              </ul>
            </details>
          )}
        </>
      )}
    </div>
  )
}
