# 交接说明（新会话从这里开始）

写这份文件的目的：换一个会话/换一个人接手时，不需要读全部历史就知道**做到哪了、下一步做什么、哪些边界不能碰**。

最后更新：2026-11-11

---

## 一、现状一句话

岗位收件箱已经能用了：**粘贴 JD 自动识别字段 → 入库 → 检索 → 一键带入匹配**；采集侧有 31 省人社厅信源模板 + 一键全抓（人工触发）。

## 二、已完成

| 模块 | 位置 | 状态 |
|---|---|---|
| 资料层（岗位/JD/笔记/面经同表） | `backend/engine/documents/` | ✅ 表结构、URL 去重、FTS5 中文检索、账号隔离、级联删除 |
| 粘贴识别 | `backend/engine/documents/paste.py` | ✅ 本地启发式：岗位名/公司/城市/薪资/年限/学历/链接，不调模型 |
| 岗位接口 | `backend/api/jobs.py` | ✅ import / list / search / detail / delete / analyze / sources / provinces / fetch-all |
| Agent 工具 | `backend/core/document_tools.py` | ✅ search_jobs / get_job / import_document（与简历质检工具分开注册） |
| 信源采集 | `backend/engine/sources/` | ✅ RSS/Atom、公告列表页、正文抽取、省份模板、一键全抓 |
| 前端 | `frontend/src/pages/jobs/` | ✅ 收件箱、详情、粘贴自动识别、信源与省份管理（管理员） |
| 文档 | `docs/plan-jobs-knowledge-community.md` | ✅ 完整方案（表结构、工具契约、分期验收、风险） |

提交记录：

```
1d95e94  feat: 新增岗位收件箱、资料检索层与 Agent 岗位工具
1665504  feat: 新增省份信源选择器与一键全抓采集
（本次） feat: 新增粘贴识别，并补充交接文档
```

## 三、下一步（按优先级）

### 1. 截图导入

**要解决的问题**：手机上刷 BOSS，复制文本比桌面麻烦，截图才是顺手的手。

**做法**：
- 复用现有 `POST /api/resume/parse-image`（视觉模型读图），拿到文字后交给 `POST /api/jobs/import`
- 前端录入区加一个「从截图导入」按钮，选图 → 上传 → 识别 → 回填到同一个表单，让用户确认后再保存
- 关键：**不要把截图识别结果直接入库**。OCR 出来的字经常串行，先让用户在表单里核对一遍，否则收件箱会被脏数据占满

**验收线**：
- 一张真实岗位截图能填出岗位名和公司（至少一个字段正确，允许用户改）
- 识别失败时给出明确提示，不写入半成品
- `test_jobs_api.py` 补一条：截图识别结果必须经过用户确认才入库（Mock 视觉模型）

### 2. 投递看板

**要解决的问题**：「我投过哪些、下一步该干嘛」现在没地方放。

**做法**：
- `applications` 表已经建好了（`stage` / `resume_snapshot_id` / `next_action_at` / `note`），直接用
- 状态机：`saved → tailored → applied → interview → offer / rejected / archived`
- 接口：`POST /api/jobs/{doc_id}/application`（推进状态）、`GET /api/jobs/applications`（列表）
- 前端：收件箱详情页加一条状态条；列表页加「投递中」筛选
- 提醒只做"下一次动作时间"，不做推送（推送要额外通道，本期不做）

**验收线**：
- 一个岗位从 `saved` 走到 `interview` 全程留痕，刷新后仍在
- 同一岗位只能有一条 `applications` 记录（已有唯一索引 `idx_applications_doc`）
- 未授权用户看不到别人的投递记录

## 四、不能碰的边界（写进 AGENTS.md 了，这里是摘要）

1. **不抓招聘平台**。BOSS/智联/猎聘的岗位只能由用户复制文本粘贴导入；粘贴的链接只记录地址，服务端不发请求。
2. **采集只人工触发**，不做定时任务。单轮 90 秒封顶、源间间隔 0.8 秒、失败只写 `last_status`。
3. **导入不依赖模型**。`parse_jd` 失败或没配模型时按原文入库，原因放 `warnings`，禁止因为模型不可用丢数据。
4. **省份模板必须如实标注 `verified`**，没实测的写 `false` 并在 `note` 说明原因，不臆造地址。
5. **新增页面要登记两处**：`App.tsx` 的 `canOpen()`（不登记点击无效）和 `setPage()` 的 `pageOverride` 分支（否则会污染工作台快照的 `page` 字段）。

## 五、常用命令

```bat
:: 启动 / 停止（前台运行，需在自己的终端里敲）
.\.venv\Scripts\python.exe start.py start
.\.venv\Scripts\python.exe start.py stop

:: 后端测试（按影响范围挑）
.\.venv\Scripts\python.exe -m unittest tests.test_documents tests.test_jobs_api tests.test_paste tests.test_sources

:: 全量回归
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"

:: 前端构建（改前端后必须做，否则浏览器还是旧包）
npm.cmd --prefix frontend run build
```

改完后端要**重启服务**；改完前端要**重启 + Ctrl+F5**（普通刷新可能用缓存的 `index.html`）。

## 六、验收基线（别把既有失败当成自己弄坏的）

`tests/test_accounts.py` 有 **2 项长期失败**，改动前就存在：

- `test_model_usage_records_provider_counts_and_isolates_accounts`
- `test_stats_count_distinct_active_users_and_current_week_registrations`

区分方法：拿改动前的提交开个临时 worktree 跑一遍对比。

```bat
git worktree add /tmp/base HEAD
/tmp/base/... -m unittest discover -s tests -p "test_*.py"
git worktree remove /tmp/base --force
```

另外 `tests/test_tool_loop.py` 是脚本式检查（不是 unittest），里面 5 条 `请先登录` 的失败也是既有的。

## 七、已知坑

| 坑 | 表现 | 解法 |
|---|---|---|
| 前端改了看不到效果 | 页面还是旧的 | 后端重启 + Ctrl+F5；确认 `frontend/dist/assets/index-*.js` 的 hash 变了 |
| `canOpen` 没登记 | 点导航完全没反应，控制台无报错 | 见边界第 5 条 |
| 写测试时 `\n` 被吃掉 | `SyntaxError: unterminated string literal` | 用 `chr(10).join([...])` 拼多行文本，别在字符串里写转义换行 |
| 政府站抓不到 | `last_status` 里是 403 / 412 / 连接失败 | 换栏目页地址；服务器出口 IP 可能被 WAF 拦，属正常 |
| 抓到的正文很短 | 存的是导航页/报名平台入口 | `min_content_chars`（默认 80）会跳过；调大更严 |
| 前端 build 报 esbuild 错 | 只显示 `Expected ";" but found ...` | 看第一行 `src/xxx.tsx:行:列`，通常是合并编辑把两行拼到一起了 |

## 八、参考资料

- 方案：`docs/plan-jobs-knowledge-community.md`
- 路线图：`ROADMAP.md`（第二期当前的进展说明在里面）
- 参考产品拆解：`../ai-product-refs/`（AIHOT / Baize / ANS / lieflat 四个案例）
- 原文存档：`../saved-articles/`
