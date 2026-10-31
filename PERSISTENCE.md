# 角色 A：工作台保存与面试记录接口

## 本次交付边界

每个账户保留一份当前求职工作台：原始文本、材料名称、JD、结构化经历、确认状态、JD 关键词、Markdown 简历和当前页面。刷新或重新登录后恢复。上传文件仅保存解析后的文字和文件名，不保存原始二进制文件；未完成的模型请求不恢复执行。多任务列表、简历版本对比、面试生成与评分不在本次范围。

保存中、保存失败、恢复失败必须可见。恢复成功前禁止编辑和写入；失败可重试。编辑后约 600 毫秒自动保存，写入串行执行；退出登录先完成待保存内容，失败时保留页面供重试。未保存时关闭页面给浏览器离开提示。跨标签页版本冲突返回 409，不自动覆盖；用户可以明确选择加载服务器版本（会放弃本页未保存编辑）。

## 账户与并发契约

所有接口要求账户 Cookie，写请求要求 `X-Requested-With: XMLHttpRequest`。新增 POST 保存请求必须携带 `expected_user_id`，服务端与当前登录账户比较，不一致返回 409，避免切换账户期间的旧页面写入新账户。DELETE 按记录 ID 和服务端当前账户共同限定，不需要请求体。不得接受客户端指定数据归属。

`GET /api/workspace` 返回 `{ok:true, revision:0, state:null, saved_at:null}` 或已有状态。`POST /api/workspace` 接收 `{expected_user_id, revision, state}`，revision 为最近读取或写入成功的版本；只有版本一致才能写入，成功后返回 `{ok:true, revision, saved_at}`。首次保存版本为 0。状态结构固定如下：

```typescript
type WorkspaceState = {
  source_text: string; source_name: string; jd_text: string;
  profile: ResumeProfile | null; jd_keywords: string[]; markdown: string;
  page: 'workbench' | 'diagnose' | 'quality' | 'interview' | 'memory';
}
```

`profile` 使用现有经历库格式。无保存记录不是错误；网络或服务错误不得当作空记录。非法结构返回 422，工作台状态序列化 JSON 的 UTF-8 大小超过 2 MiB 返回 413。恢复保存中的确认状态不代替用户核对；编辑经历或 JD 继续按已有规则撤销确认和清空旧稿。

## 面试记录（交角色 C 接入）

`POST /api/interview-records` 接收 `{expected_user_id, title, jd_text, questions, answers, question_scores, overall_feedback}`。questions 为对象数组，answers 为字符串数组，question_scores 为对象数组，overall_feedback 为对象；允许保存尚未评分的记录，字段默认空数组或空对象。这里只存储，不产生评分、不证明评分内容正确。每次 POST 创建独立记录，调用方应在一轮结束后提交一次，避免重复点击。

成功返回 `{ok:true, id, saved_at}`。`GET /api/interview-records` 返回 `{ok:true, records:[{id,title,saved_at}]}`，按时间倒序。`GET /api/interview-records/{id}` 返回 `{ok:true, record:{id,title,saved_at,jd_text,questions,answers,question_scores,overall_feedback}}`。`DELETE /api/interview-records/{id}` 删除成功返回 `{ok:true}`。未知或其他账户记录统一 404。

前端将记录 ID 放入 URL 路径时必须使用 `encodeURIComponent`，确保 ID 始终作为单一路径段传输。保存请求中的 `expected_user_id` 必须来自本轮开始时的账户身份。

单条面试记录序列化 JSON 的 UTF-8 大小限制为 1 MiB，标题最多 200 字符；超出记录大小返回 413，结构或标题不合法返回 422。记录存储在本机已有 SQLite 数据库，不依赖外部模型。暂不保留原始录音，不提供跨账户访问。

## 文件分工与交接

- A：`backend/core/accounts.py` 新表、独立保存路由、`backend/main.py` 注册、`frontend/src/App.tsx`、`frontend/src/lib/api.ts` 和独立保存状态模块。
- B：继续负责工作台页面。A 只将 `sourceText/sourceName` 改为由 App 传入的受控属性，并传入对应 setter，其他交互保持现有行为。后续页面改造需保留这些属性。
- C：继续负责 `backend/api/interview.py` 与面试页面。使用 `api.saveInterviewRecord/listInterviewRecords/loadInterviewRecord/deleteInterviewRecord` 接入历史；A 不改生成或评分行为。
- D：继续使用现有 `/api/profiles/*` 管理确认经历，不另建共享资料库；导出使用当前 Markdown。

角色 C 的保存调用示例（`user.id` 使用本轮面试开始时的账户，不在提交时重新从 `/auth/me` 取另一个账户）：

```typescript
await api.saveInterviewRecord(user.id, {
  title: '产品经理 · 第一轮',
  jd_text: jdText,
  questions,
  answers,
  question_scores: questionScores,
  overall_feedback: overallFeedback,
})
const history = await api.listInterviewRecords()
const detail = await api.loadInterviewRecord(history.records[0].id)
```

面试页面接入时由 A 将当前 `user.id` 作为属性传入；当前面试页面尚不自动调用记录接口。保存失败应展示错误并保留本轮作答，成功拿到 id 后禁止本轮重复提交。

## 验收

临时数据库验证恢复、账户隔离、缺少登录/请求头、无效结构、版本冲突、错误账户写入和面试记录读写删除。浏览器验证原始文本/JD 刷新恢复、保存错误提示与重试、恢复失败阻止写入、跨标签页冲突和退出保存。外部模型沿用现有 Mock 边界，不以本次存储测试冒充真实模型验证。
