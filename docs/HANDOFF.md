# 交接说明（新会话从这里开始）

写这份文件的目的：换一个会话/换一个人接手时，不需要读全部历史就知道**做到哪了、文档在哪、哪些坑别再踩**。
排期与勾选状态**不在本文件**，统一看 [BACKLOG.md](BACKLOG.md)（唯一排期文档）。

最后更新：2026-11-12

## 一、现状一句话

简历工作台（材料 → 确认事实 → 检查优化 → 预览导出）、模拟面试、个人经历库、岗位收件箱（粘贴/截图
导入 + 31 省信源 + 投递看板 + 一键匹配→定制→质检）、面经与内推社群、管理员后台（统计/反馈/角色/
联系方式/错误趋势）都已可用；**全量回归 374 项全绿**。

## 二、文档在哪

| 想知道什么 | 看哪 |
| --- | --- |
| 做到哪了、还剩什么、每项验证到什么程度 | [BACKLOG.md](BACKLOG.md) |
| 哪些行为不能违反 | [AGENTS.md](../AGENTS.md) |
| 本机怎么起、怎么重启、怎么验证 | [RUNBOOK.md](../RUNBOOK.md) |
| 服务器怎么部署、环境变量有哪些 | [DEPLOY.md](../DEPLOY.md) |
| 账户/经历库/持久化/模型错误/社群契约 | 根目录 `ACCOUNT.md`、`LIBRARY.md`、`PERSISTENCE.md`、`MODEL_ERRORS.md`、`docs/COMMUNITY.md` |

## 三、代码地图（找东西用）

```
backend/api/          接口层（jobs / resume / diagnose / quality / interview* / community / user_stats …）
backend/core/         账户、模型客户端、事件流、event_log（错误统计）
backend/engine/documents/   岗位/资料层、粘贴识别、截图转写、投递看板
backend/engine/community/   面经卡片、脱敏、评论文本、面经转题（peer_questions）
backend/engine/knowledge/   术语归一（terms）、范例检索（examples）
backend/engine/sources/     RSS/公告列表抓取、31 省模板
backend/tools/        运维脚本（audit_provinces 省份巡检）
frontend/src/pages/   页面（workbench / jobs / community / interview / library …）
tests/test_*.py       unittest 用例（discover 只跑这些）
tests/run_*_qa.py     脚本式检查（单独运行，不参与 discover）
```

## 四、常用命令

```bat
:: 启停（start 占住当前终端；停止另开终端或 Ctrl+C）
.\.venv\Scripts\python.exe start.py start
.\.venv\Scripts\python.exe start.py stop

:: 全量回归（当前应全绿）
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"

:: 前端
npm.cmd --prefix frontend run build
npm.cmd --prefix frontend exec vitest run

:: 管理员开通（部署时忘了配名单）
.\.venv\Scripts\python.exe backend/manage.py admin grant 用户名

:: 省份信源巡检（加 --write 才回写模板）
.\.venv\Scripts\python.exe backend/tools/audit_provinces.py
```

改完后端要**重启服务**；改完前端要**重启 + Ctrl+F5**（普通刷新可能命中旧缓存）。

## 五、已知坑

| 坑 | 表现 | 解法 |
| --- | --- | --- |
| 前端改了看不到效果 | 页面还是旧的 | 后端重启 + Ctrl+F5；确认 `frontend/dist/assets/index-*.js` hash 变了 |
| `canOpen` 没登记 | 点导航没反应、控制台无报错 | 新页面要同时登记 `App.tsx` 的 `canOpen()` 与 `setPage()` 的 `pageOverride` 分支 |
| 写测试时 `\n` 被吃掉 | `SyntaxError: unterminated string literal` | 用 `chr(10).join([...])` 拼多行文本，别在字符串里写转义换行 |
| 脚本式检查混进 discover | 串扰其它用例、改全局 | 一律命名 `tests/run_*_qa.py`，不要在 import 时执行检查（见 AGENTS.md） |
| 公共岗位池操作报"不存在" | 采集来的岗位 `user_id` 为 NULL | 权限判断统一走 `store.get_document()`，不要手写 owner 相等 |
| 政府站抓不到 | `last_status` 是 403 / 412 / 证书错误 | 站点侧限制；跑巡检脚本如实标 `verified: false`，不硬刚 |
| 抓到的正文很短 | 存的是导航页/报名入口 | `min_content_chars`（默认 80）会跳过；调大更严 |
| 截图转写全角冒号变半角 | 结果走了 `normalize_text` | 正常现象，测试只断言关键内容 |
| 薪资识别成职责里的一句话 | 行里有 `Workflow`，单个 `k` 被当成 K | 已修：只认薪资字段行，解析不出数字就留空 |
| 一键链路没配模型却显示"匹配失败" | `diagnose` 的宽 `except` 吞了 428 | 已修：`HTTPException` 原样抛出 |

区分"我弄坏的"还是"本来就坏的"：拿改动前的提交开临时 worktree 跑一遍对比。

```bat
git worktree add /tmp/base HEAD
/tmp/base/... -m unittest discover -s tests -p "test_*.py"
git worktree remove /tmp/base --force
```

## 六、参考资料

- 参考产品拆解：`../ai-product-refs/`（AIHOT / Baize / ANS / lieflat）
- 原文存档：`../saved-articles/`
- 界面与海报源文件：仓库根目录 `职得offer-*.png/pdf`
