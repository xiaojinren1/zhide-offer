# 岗位收件箱 · 资料检索 · 弱实名社群 实施方案

- 状态：待开发（第一期"简历美化与在线分享"收尾后开工）
- 对应路线图：第二期 / 第三期 / 第四期 / 第五期
- 编写依据：仓库现有代码（`backend/` 5673 行、`engine/` 3056 行、24 个测试文件、`ROADMAP.md` 当前规划）

---

## 0. 核心判断（决定整个方案的结构）

**"岗位收件箱"和路线图里原有的"私有资料区"底层是同一个东西——一份「资料」。**

岗位 JD、用户自己上传的 JD、面试复盘、技术笔记，差别只在 `kind` 和 `source`。做成两套表会重复劳动两遍；做成一层，只多两个字段，而且检索、投稿、社群审核全部复用同一条链路。

因此本方案的改造顺序是：**先统一资料层 → 再把检索建在同一层上 → 再把"私有资料"公开化变成社群内容**。

三个原则：
1. 服务端不直连招聘平台（合规 + 维护成本）
2. Agent 工具化优先于页面化（`tools.py` 现有原则：程序可判、结构化返回、失败不抛异常）
3. 每期有可复现的验收脚本，验收不过不进下一期

---

## 1. 边界

### 做

- 岗位进得来：公开源自动采集 + 粘贴链接 + 粘贴正文 + 上传截图
- 资料能检索：私有库 + 公开库，检索接到「匹配 / 改写 / 面试」三个决策点
- 投递有看板：状态机 + 提醒 + 全流程留痕
- 面经/内推/JD 评价可投稿、可审核、可匿名查看

### 不做（写死，避免反复纠结）

| 不做 | 原因 |
|---|---|
| 服务端爬 BOSS / 智联 / 猎聘 | 违用户协议 + 签名/滑块/设备指纹持续对抗，且商业化后投诉风险高 |
| 自动投递、自动打招呼 | 平台违规，且对用户是负价值 |
| 实时聊天社区 | 单人无法维护；求职者 3 个月一波流，聊天型社区必然冷掉 |
| 手机号/学信网级实名 | 成本远大于收益 |
| 浏览器扩展 | 本期不做（上架、审核、改版跟进都是长期成本） |

### 粘贴链接的处理约定（写进代码注释）

```
对用户粘贴的 URL 只尝试抓取一次公开可见内容：
- 成功 → 存结构化字段 + 正文 + 来源 URL，不存原始 HTML
- 失败（403 / 需登录 / 验证码）→ 立即降级，提示"请用截图或粘贴正文"
- 不重试、不绕验证码、不换 UA 硬刚、不请求列表接口
```

### 截图导入的处理约定（写进代码注释）
```
截图只用于「把图读成字」：
- POST /api/jobs/parse-image：校验格式/大小/像素 → 视觉模型只转写文字
  → 本地 paste.analyze 猜字段 → 一起回填到录入表单，不入库
- 用户核对、可改、自己点「保存到收件箱」，才走 POST /api/jobs/import（source=image）
- 识别失败或读出字数过少：返回 {ok:false, error}，不返回半成品、不写任何记录
- 原图不落盘；图片只发给用户自己配置的图片模型（与简历图片解析同一套边界）
```

理由：截图 OCR 经常串行、串字段，直接入库等于把错误固化成“事实”，收件箱会被脏数据占满。

同一原则适用于薪资字段：识别只在看起来是薪资字段的行内进行（带“薪资/待遇/工资”等字段词，
或短到只剩 `20-35K·14薪`）；职责、任职要求这类语句行一律不算。解析不出数字（包括平台脱敏的
`**-***元`）就留空并提示用户手动填，不允许拿职责句里的数字当工资。

---

## 2. 数据模型

```sql
-- ① 统一资料层
CREATE TABLE IF NOT EXISTS documents (
    id              TEXT PRIMARY KEY,
    user_id         TEXT REFERENCES users(id) ON DELETE CASCADE,  -- NULL = 公共岗位池
    kind            TEXT NOT NULL,   -- job | jd | note | review | tech
    source          TEXT NOT NULL,   -- upload | paste | image | feed | manual
    source_key      TEXT NOT NULL,   -- 去重键：规范化 URL 的 hash 或正文 simhash
    title           TEXT NOT NULL DEFAULT '',
    company         TEXT NOT NULL DEFAULT '',
    role            TEXT NOT NULL DEFAULT '',
    city            TEXT NOT NULL DEFAULT '',
    salary_text     TEXT NOT NULL DEFAULT '',    -- 原文展示用
    salary_min      INTEGER,                     -- 元/月
    salary_max      INTEGER,
    experience      TEXT NOT NULL DEFAULT '',
    education       TEXT NOT NULL DEFAULT '',
    url             TEXT NOT NULL DEFAULT '',
    published_at    REAL,
    fetched_at      REAL NOT NULL,
    content_md      TEXT NOT NULL DEFAULT '',
    structured_json TEXT NOT NULL DEFAULT '{}',  -- 要求列表、关键词、技能族、归一标签
    visibility      TEXT NOT NULL DEFAULT 'private', -- private | pending | public | rejected
    review_note     TEXT NOT NULL DEFAULT '',
    reviewed_by     TEXT,
    reviewed_at     REAL,
    license_note    TEXT NOT NULL DEFAULT '',    -- 来源与可公开性备注
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_dedupe ON documents(COALESCE(user_id, ''), source_key);
CREATE INDEX IF NOT EXISTS idx_documents_kind ON documents(COALESCE(user_id, ''), kind, updated_at DESC);

-- ② 检索层
CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id      TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    user_id     TEXT,
    chunk_index INTEGER NOT NULL,
    text        TEXT NOT NULL,
    text_tokens TEXT NOT NULL,   -- 中文二元组 + 拉丁词，空格连接（不依赖 jieba）
    tokens      INTEGER NOT NULL DEFAULT 0
);
-- FTS5 用独立表，不用外部内容表：分块写入与重建由 store.replace_chunks() 显式同步。
-- 不用触发器的理由：触发器写错会静默丢索引，排查成本远高于显式同步。
CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(text_tokens, chunk_id UNINDEXED);

-- ③ 投递看板
CREATE TABLE IF NOT EXISTS applications (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    doc_id      TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    stage       TEXT NOT NULL DEFAULT 'saved',  -- saved|tailored|applied|interview|offer|rejected|archived
    resume_snapshot_id TEXT,
    next_action_at REAL,
    note        TEXT NOT NULL DEFAULT '',
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
);

-- ④ 社群
CREATE TABLE IF NOT EXISTS anon_identities (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    display_name TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS public_cards (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    anon_id TEXT NOT NULL REFERENCES anon_identities(id),
    kind TEXT NOT NULL,            -- interview_exp | referral | jd_review
    company TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL DEFAULT '',
    round TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    body_md TEXT NOT NULL,
    tags_json TEXT NOT NULL DEFAULT '[]',
    structured_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending',  -- pending | public | rejected
    review_note TEXT NOT NULL DEFAULT '',
    reviewed_by TEXT,
    reviewed_at REAL,
    helpful_count INTEGER NOT NULL DEFAULT 0,
    report_count INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    published_at REAL
);

-- ⑤ 信源
CREATE TABLE IF NOT EXISTS feed_sources (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,      -- rss | json | html_list | manual
    url TEXT NOT NULL,
    tier INTEGER NOT NULL DEFAULT 3,   -- 1 官方一手 / 2 官方转载 / 3 媒体聚合
    enabled INTEGER NOT NULL DEFAULT 1,
    last_run_at REAL,
    last_status TEXT NOT NULL DEFAULT ''
);
```

**四个设计要点**

1. `source_key` 去重是采集的生命线：同一岗位抓十次只能有一条
2. `visibility` 一个字段同时管私库和社群：投稿 = `private → pending`，审核通过 `→ public`，不需要第二套体系
3. `license_note` 记来源与可公开性，便于处理删除请求
4. `structured_json` 存归一化结果，模型换代时可整批重跑，不丢历史

**迁移注意**：现有 `users` 表没有 email 字段，弱实名若上 L1 需要 `ALTER TABLE users ADD COLUMN email / email_verified_at / email_domain_tag`，必须写成兼容旧库的幂等迁移。

---

## 3. 模块与文件清单

```
新增
backend/engine/documents/schema.py     建表与幂等迁移
backend/engine/documents/normalize.py  JobDraft → Document，字段清洗与归一
backend/engine/documents/dedupe.py     URL 规范化、simhash、去重判定
backend/engine/documents/chunk.py      分段 + jieba 分词
backend/engine/sources/base.py         适配器协议
backend/engine/sources/*.py            每个源一个文件
backend/engine/knowledge/index.py      写索引（FTS5 + 可选 vec）
backend/engine/knowledge/retrieve.py   混合检索与排序
backend/engine/applications/state.py   状态机与提醒计算
backend/engine/community/anonymous.py  马甲生成与映射
backend/engine/community/review.py     审核状态机
backend/engine/community/redact.py     入库前脱敏
backend/api/jobs.py                    search / save / track / import
backend/api/knowledge.py               search / contribute
backend/api/community.py               cards / report / review
frontend/src/pages/jobs/               收件箱、详情、投递看板
frontend/src/pages/community/          面经库、内推墙、投稿

修改
backend/core/tools.py                  新增 6 个工具
backend/engine/matcher.py              接入术语归一检索
backend/engine/tailoring.py            接入范例检索
backend/engine/example_lib.py          改为从 documents 读，examples.json 作为种子
frontend/src/App.tsx                   FLOW 增加"岗位"步，sidebar 增加"资料库""社区"
backend/data/knowledge/examples.json   保留为种子数据，首次启动导入一次
```

**信源适配器协议**

```python
class SourceAdapter(Protocol):
    name: str
    tier: int  # 1 官方一手 / 2 官方转载 / 3 媒体聚合

    def fetch(self, cursor: str | None) -> Iterable[RawItem]: ...
    def normalize(self, raw: RawItem) -> DocumentDraft: ...
    def dedupe_key(self, draft: DocumentDraft) -> str: ...
```

首批三个源：省级人社/国资公开招聘公告（HTML 列表）、高校就业信息网校招公告（HTML 列表）、一个有 JSON 接口的企业官网。单源失败不影响整体；管理后台加"试抓"按钮。

---

## 4. Agent 工具契约

沿用 `backend/core/tools.py` 现有原则：程序可判、结构化返回、失败以 `{"error": ...}` 返回而不抛异常、描述写清"什么时候该用"。

```
search_jobs(query, city?, salary_min?, source?, limit=10)
  → {items: [{job_id, title, company, city, salary, match_hint}]}
  说明：用户说想找某类工作时调用；返回 job_id 供 get_job 消费

get_job(job_id)
  → {job_id, title, company, content_md, requirements[], structured}

import_document(text?, url?, image_ref?)
  → {doc_id, kind, parsed_ok, warnings[]}
  说明：用户给出链接、正文或截图时调用；失败返回 warnings 而不是报错

save_application(job_id, stage, note?)
  → {ok, stage, next_action_at}

search_knowledge(query, scopes=["private","public"], limit=5)
  → {hits: [{chunk_id, doc_id, title, excerpt, score, source_type}]}
  说明：改写简历前检索同岗位范例；匹配前检索术语归一

get_interview_experience(company, role?)
  → {cards: [{round, title, excerpt, helpful_count}], total}
```

**验收工具链**：`search_jobs → get_job → search_knowledge → 定制简历 → check_resume_quality → save_application` 必须能在一次会话内跑通。

---

## 5. 检索设计

**索引**：jieba 预分词写入 `text_tokens`，FTS5 用默认 tokenizer。中文不要用 trigram（3 字以下查不到），也不要指望 unicode61 直接切中文。

**排序**：`score = 0.6 * bm25_norm + 0.3 * vec_norm + 0.1 * recency`（无 embedding 时退化为 BM25 + recency）。

**三个接入点**

| 接入点 | 检索什么 | 收益 | 验证方法 |
|---|---|---|---|
| `matcher.py` | 技能族 / 岗位别名 / 行业术语 | 提升召回，直接改善"覆盖/缺失"判断 | 30 条 JD 接前接后 covered 数对比 |
| `tailoring.py` | 同岗位 STAR 范例 | 用户可感知（写得更像行内人） | 10 对人工盲评 |
| `interview_v2.py` | 面经 / 题目 | 传播性最强 | 生成追问的"有据率" |

**红线**：公开库不存别人简历原文。公开卡片只收结构化题目和面经，入库前脱敏（先做 12 条规则：手机号、邮箱、身份证、姓名、公司内部代号、工号、住址、学校邮箱、QQ/微信、车牌、银行卡、内部系统域名）。

---

## 6. 弱实名方案

`users` 表现状：`id / username / password_hash / avatar / recovery_code_hash / created_at / guest_until` —— **没有 email，没有验证通道**。

| 档 | 做法 | 成本 | 效果 |
|---|---|---|---|
| **L0 账号可追溯 + 马甲匿名**（本期先上） | 内容绑 `user_id`，对外只显示马甲；映射加密存储，仅举报处理时管理员可见并留审计 | 1 天，0 元 | 平台能追责，用户敢说话 |
| **L1 邮箱验证 + 域名标签**（随后） | `edu.cn` → 学生；企业域 → 在职；个人域 → 普通。未验证也能看和投稿，只影响排序与审核优先级 | 2–3 天（需 SMTP：阿里云邮件推送 / Resend） | 有"认证感"，天然分出校招/社招两个池 |
| L2 手机号 / 学信网 | — | 高 | 本期不做 |

**审核状态机**

```
pending → public    （通过，记录 reviewed_by / reviewed_at）
pending → rejected  （退回，review_note 必填）
public  → rejected  （举报成立，保留原因）
```

**只有 `public` 出现在任何列表里**——必须写在 SQL 查询条件里，不能靠前端过滤。

---

## 7. 分期与验收

> 第一期（简历美化 + 在线分享）正在做，不打断。以下从第二期开始。

| 期 | 内容 | 周期 | 验收线 |
|---|---|---|---|
| **二 · 岗位收件箱** | `documents` + `feed_sources` + 适配器协议 + 3 个公开源 + 粘贴/截图导入 + `pages/jobs` + 3 个工具 | 2 周 | 50 条真实岗位入库；同 URL 重复抓取只有 1 条；任一岗位一键跑通「匹配→定制→质检」；`tests/test_jobs_ingest.py` 全绿；前端 `npm run build` 通过 |
| **三 · 资料检索与知识库** | `knowledge_chunks` + FTS5 + 私有资料区（上传/编辑/标签/搜索/删除）+ 投稿审核链路 + 三处接入 | 2–3 周 | 30 条 JD 接前接后 covered 数提升 ≥10%，用 `tests/run_retrieval_ab.py` 复现；检索 P95 < 100ms |
| **四 · 投递看板与 Agent 闭环** | `applications` 状态机 + 提醒 + 关联简历快照与面试记录 + 全流程工具化 | 1.5 周 | 一个岗位从 `saved` 走到 `interview` 全程留痕；agent 单次会话能连做 3 步 |
| **五 · 弱实名社群** | `anon_identities` + `public_cards` + 一键提审 + 举报 + 三张卡页面 | 3–4 周 | 10 条非管理员提交的卡片上线；未审核不可见；举报 24h 内可处置；脱敏测试通过 |
| **六 · 管理员错误统计** | 沿用原规划：近 24 小时 / 近 7 天错误趋势、错误分类、脱敏明细 | 0.5 天 | 普通用户无权读取；后台不显示密钥、简历正文或原始请求 |

**不做并行**。每期结束更新 `ROADMAP.md` 状态并记录已验证范围。

---

## 8. 风险与对策

| 风险 | 对策 |
|---|---|
| 公开源改版，适配器失效 | 适配器隔离 + 单源失败不影响整体 + 后台"试抓" + `last_status` 告警 |
| 用户粘贴的链接被平台挡 | 只抓一次，失败即降级"截图/粘贴正文"，不重试 |
| 模型成本随资料量上涨 | 批量解析/归一/打标走便宜模型；强模型只在用户等待的那一步出现 |
| SQLite 增长 | 公开源岗位与用户私库分表，定期归档 + vacuum；单用户量级完全撑得住 |
| 合规投诉 | 关于页加来源与版权声明 + 删除请求入口 + `license_note` 可定位；公开卡片入库前脱敏 |
| 改动与在做的功能交叉 | 开工前 `git status` 确认范围，只改本期文件，不动未提交的在做改动 |

---

## 9. 开工顺序

```
1. documents / knowledge_chunks / applications 建表 + 幂等迁移 + tests/test_documents.py
2. sources/base.py + 第一个适配器（省人社厅公告，最稳）+ 入库去重
3. api/jobs.py + 前端收件箱最小版（列表 + 详情 + 一键匹配）
4. tools.py 三个工具 + tool loop 跑通一条真实链路
5. 进第三期检索
```

---

## 10. 附录

- **提交格式**：本项目 `AGENTS.md` 要求 `类型: 中文描述`（冒号后一个空格）；与全局偏好 `类型:中文描述`（无空格）相反。按项目规范执行，已与作者确认。
- **前端验证**：`npm.cmd --prefix frontend run build`
- **后端验证**：按影响范围跑相关测试，外部依赖优先 Mock；真实调用另行说明
- **参考实现**：信源适配器与配置分层参考 AIHOT（MIT），脱敏规则参考 Baize（MIT）。两者许可允许商用，但需保留版权声明且不得沿用品牌。
