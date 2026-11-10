# 模拟面试接口与集成

## 已接入

- 保留 InterviewPage 的 jdText、profile、markdown 属性，新增可选 userId；优先使用 App 的当前账户 ID，缺省通过现有 api.me 加载。
- 复用 core.llm.chat_json、LLMError 及现有模型配置；未配置或上游异常时返回现有 503/429/504/502 分类，模型输出经严格字段及证据校验。
- backend/api/interview.py 包含新路由，沿用 main 中已有登录和 CSRF 保护，旧接口兼容保留。
- 复用账户 SQLite 和 interview_records API。临时 interview_artifacts 表由面试专用模块初始化，记录只按服务端账户 ID 查写；expected_user_id 仅用于拒绝过期账户请求。

## 新接口

所有请求为 POST JSON，携带 Cookie 与 `X-Requested-With: XMLHttpRequest`。共同必填 expected_user_id 和 UUID request_id。相同请求重试必须保留整个请求体，不能在重试时重新计算 elapsed_seconds。

| 路径 | 业务参数 | 响应 |
| --- | --- | --- |
| /api/interview/bank | resume_profile、resume_markdown、jd_text | `{ok, bank}`；bank 包含 id、job_title、snapshot、sources、questions（10–30 项，拒绝规范化后重复题） |
| /api/interview/start（题库） | bank_id；不得同时提交材料字段 | `{ok, session}`；mode=bank，沿用题库冻结材料及能力主题 |
| /api/interview/start（直接） | resume_profile、resume_markdown、jd_text；不得同时提交 bank_id | 同上；mode=direct、bank_id=null，一次模型调用生成主题与首问，无题库和示范 |
| /api/interview/turn（旧开始兼容） | bank_id | 保留旧客户端兼容，新页面统一调用 /start |
| /api/interview/turn（回答） | session_id、version、answer 或 skip、elapsed_seconds | 同上；成功后版本递增，失败不追加回答 |
| /api/interview/report | session_id、version、elapsed_seconds、final_answer（可空） | `{ok, session, report, saved, save_error, record_id}`；报告失败重试原请求，保存失败保留报告 |

题库 ID 为 bank-请求 UUID，会话 ID 为 session-开始请求 UUID。session 包含首题、version、status、turns、elapsed_seconds、mode、snapshot，不返回示范或分数。直接模式内部 context 仅保留岗位、事实来源、主题和材料，不预生成后续问题；两种模式共享动态 /turn 和 /report。turn 的 bank_id/session_id 二选一，version 为服务端最近返回值。回答最多 12000 字。409 为内容或账户冲突；410 表示记录已删除，不能通过旧结束请求恢复。

报告 report 包含 overall_score、kind（complete/partial）、五维 dimensions、HR/interviewer_feedback、strengths、improvements、optimized_answers、recommendations 和 coverage。得分需有真实回答逐字引用；少于三次非跳过作答或任何维度未充分考察时，overall_score 为 null。权重各 20%。完整结构见 types.ts 和 backend/engine/interview_v2.py。

## 完成记录格式

使用既有读取、列表和删除接口 `/api/interview-records`。record 的 questions/answers 保存问答，question_scores 为空数组，overall_feedback 为：

```json
{
  "schema_version": 3,
  "mode": "direct",
  "snapshot": {"resume_profile": {}, "resume_markdown": "...", "jd_text": "...", "captured_at": "..."},
  "context": {"job_title": "...", "sources": [], "topics": [], "resume_markdown": "...", "jd_text": "..."},
  "bank": null,
  "transcript": [],
  "report": {},
  "elapsed_seconds": 0
}
```

此例只说明存储结构，不是可提交的业务样例。题库模式 mode=bank，bank 为 job_title、questions、sources；直接模式为 null。不新增数据库表，沿用现有 interview_artifacts 和 interview_records。保存上限沿用现有 1 MiB。相同会话仅一条历史；历史和“曾保存”标记同事务写入，迟到重试不能重建已删除记录。版本 2 按旧结构回看，不用新题量规则拦截历史题库；更早旧版记录只读展示，并标明旧规则评分。进行中的版本 2 会话可继续对话并生成版本 3 历史。
