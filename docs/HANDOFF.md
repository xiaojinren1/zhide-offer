# 交接说明（新会话从这里开始）

写这份文件的目的：换一个会话/换一个人接手时，不需要读全部历史就知道**做到哪了、下一步做什么、哪些边界不能碰**。

最后更新：2026-11-12

---

## 一、现状一句话

岗位收件箱已经能用了：**粘贴 JD 自动识别字段 / 截图转写回填 → 入库 → 检索 → 一键带入匹配**；采集侧有 31 省人社厅信源模板 + 一键全抓（人工触发）。

## 二、已完成

| 模块 | 位置 | 状态 |
|---|---|---|
| 资料层（岗位/JD/笔记/面经同表） | `backend/engine/documents/` | ✅ 表结构、URL 去重、FTS5 中文检索、账号隔离、级联删除 |
| 粘贴识别 | `backend/engine/documents/paste.py` | ✅ 本地启发式：岗位名/公司/城市/薪资/年限/学历/链接，不调模型 |
| 截图导入 | `backend/engine/documents/screenshot.py` + `POST /api/jobs/parse-image` | ✅ 视觉模型只转写文字，回填表单等用户确认后才入库（Mock + 真实页面已验证；真实视觉模型待配置后实测） |
| 岗位接口 | `backend/api/jobs.py` | ✅ import / list / search / detail / delete / analyze / parse-image / sources / provinces / fetch-all |
| Agent 工具 | `backend/core/document_tools.py` | ✅ search_jobs / get_job / import_document（与简历质检工具分开注册） |
| 信源采集 | `backend/engine/sources/` | ✅ RSS/Atom、公告列表页、正文抽取、省份模板、一键全抓 |
| 前端 | `frontend/src/pages/jobs/` | ✅ 收件箱、详情、粘贴自动识别、截图导入（回填表单）、信源与省份管理（管理员） |
| 文档 | `docs/plan-jobs-knowledge-community.md` | ✅ 完整方案（表结构、工具契约、分期验收、风险） |
| 面经与内推（社群） | `backend/engine/community/` + `api/community.py` + `pages/community/` | ✅ 匿名投稿 → 审核 → 公开、有帮助、举报、撤回；契约见 `docs/COMMUNITY.md` |
| 管理员开通 CLI | `backend/manage.py` | ✅ `admin grant/revoke/list`，无管理员时启动日志给出补救命令 |

提交记录：

```
1d95e94  feat: 新增岗位收件箱、资料检索层与 Agent 岗位工具
1665504  feat: 新增省份信源选择器与一键全抓采集
5e80283  feat: 新增粘贴识别与交接文档
（本次） feat: 新增岗位截图转写导入（识别后由用户确认入库）
```

## 三、下一步（按优先级）

### 1. 投递看板

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

### 2. 社群 v1 还差的东西

已经能跑：匿名投稿 → 审核（退回必填理由）→ 公开、有帮助（可撤回）、举报（进管理员队列，
累计 3 条自动撤下）、管理员下架/删除、作者随时撤回、被退回/下架后编辑或重新提交再进待审（编辑算新版本：旧帮助票作废、旧评论折叠标注、旧举报结案；
作者/管理员可查历史版本并与上一版做行级对比）、
卡片下匿名评论（即时公开，被举报 2 条撤下可恢复），见 [COMMUNITY.md](COMMUNITY.md)。

- `anon_identities` 的账号映射是**明文**存库，方案里写的"加密存储"没做；处理举报只靠管理员权限。
- 没有弱实名（邮箱/域名标签）；举报已记录处理人和时间（`card_reports.status/handled_by`），
  但还没有处置时效统计与提醒。
- 没有从面经卡片一键生成面试题/关联到面试记录；评论没有盖楼与 @。

## 四、不能碰的边界（写进 AGENTS.md 了，这里是摘要）

1. **不抓招聘平台**。BOSS/智联/猎聘的岗位只能由用户复制文本粘贴导入；粘贴的链接只记录地址，服务端不发请求。
2. **采集只人工触发**，不做定时任务。单轮 90 秒封顶、源间间隔 0.8 秒、失败只写 `last_status`。
3. **导入不依赖模型**。`parse_jd` 失败或没配模型时按原文入库，原因放 `warnings`，禁止因为模型不可用丢数据。
4. **截图只做转写，不入库**。`/api/jobs/parse-image` 把图读成文字回填表单，用户核对后自己点保存才入库；识别失败不写半成品、不改动正文。
5. **社群只出 public**。`public_cards` 的状态机是 `pending → public / rejected`，公开列表在 SQL 里限定 `status='public'`；对外只给匿名马甲，接口不得返回 `user_id` / `anon_id`；投稿入库前必须脱敏，退回必须写理由。
6. **薪资认不准就不写**。只在薪资字段行内识别（带薪资字段词，或短到只剩 `20-35K·14薪`）；职责句、脱敏的 `**-***元`、解析不出数字的文本都留空并提示，绝不拿职责里的数字当工资。
7. **省份模板必须如实标注 `verified`**，没实测的写 `false` 并在 `note` 说明原因，不臆造地址。
8. **新增页面要登记两处**：`App.tsx` 的 `canOpen()`（不登记点击无效）和 `setPage()` 的 `pageOverride` 分支（否则会污染工作台快照的 `page` 字段）。

## 五、常用命令

```bat
:: 启动 / 停止（start 会占住当前终端；停止在另一个终端执行，或直接 Ctrl+C）
.\.venv\Scripts\python.exe start.py start
.\.venv\Scripts\python.exe start.py stop

:: 后端测试（按影响范围挑）
.\.venv\Scripts\python.exe -m unittest tests.test_documents tests.test_jobs_api tests.test_paste tests.test_sources

:: 全量回归
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"

:: 前端构建（改前端后必须做，否则浏览器还是旧包）
npm.cmd --prefix frontend run build

:: 管理员开通 / 查看（部署时忘了配名单就用它补）
.\.venv\Scripts\python.exe backend/manage.py admin list
.\.venv\Scripts\python.exe backend/manage.py admin grant 用户名
```

改完后端要**重启服务**；改完前端要**重启 + Ctrl+F5**（普通刷新可能用缓存的 `index.html`）。

细节见 [RUNBOOK.md](../RUNBOOK.md)：`start` 要求 `frontend/dist/index.html` 存在，进程号记在 `data/local-server.pid.json`；绕开 `start.py` 直接跑 `backend/main.py` 启动的进程无法用 `stop` 关闭。服务器用 systemd 启停，不用 `start.py`，见 [DEPLOY.md](../DEPLOY.md)。

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
| 点「从截图导入」提示配置模型 | 428「请先在模型设置中配置并启用图片解析模型」 | 截图转写用的是**图片**模型（与简历图片解析共用），不是文本模型 |
| 截图转写全部换行变多/全角冒号变半角 | 转写结果走了 `normalize_text` 的 NFKC 归一 | 正常现象；测试里只断言关键内容，不整体比对原文 |
| 薪资识别出来是职责里的一句话 | 行里有 `Workflow`，单个 `k` 被当成“K”，`min=max=2` | 已修：只认薪资字段行（`paste._salary_candidate`），解析不出数字就留空 |
| 平台脱敏薪资 `**-***元` | 存成乱码或猜成数字 | 已修：留空 + 提示“薪资被平台脱敏，需要自己填” |
| 政府站抓不到 | `last_status` 里是 403 / 412 / 连接失败 | 换栏目页地址；服务器出口 IP 可能被 WAF 拦，属正常 |
| 抓到的正文很短 | 存的是导航页/报名平台入口 | `min_content_chars`（默认 80）会跳过；调大更严 |
| 前端 build 报 esbuild 错 | 只显示 `Expected ";" but found ...` | 看第一行 `src/xxx.tsx:行:列`，通常是合并编辑把两行拼到一起了 |

## 八、参考资料

- 方案：`docs/plan-jobs-knowledge-community.md`
- 路线图：`ROADMAP.md`（第二期当前的进展说明在里面）
- 参考产品拆解：`../ai-product-refs/`（AIHOT / Baize / ANS / lieflat 四个案例）
- 原文存档：`../saved-articles/`
