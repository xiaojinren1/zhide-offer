# 职得offer：本机启动与今晚交接

## 当前阶段
保留 FastAPI + React + TypeScript 工程。今晚先交付本机工作台骨架，明天按实测情况分工。需求以 TONIGHT.md 及 v0.5 方案为参考，最终已交付范围以本文件的验证记录为准。

## 环境准备（Windows PowerShell）
需要 Python 3.12+、Node.js 22+、PowerShell 7。不要把 WindowsApps 的 Python 别名当成已安装的解释器。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
npm.cmd --prefix frontend ci
npm.cmd --prefix frontend run build
```

已有项目 .venv 时无需重建。当前负责人的本机已创建并安装依赖。

## 模型配置
若 backend/.env 不存在，将 backend/.env.example 复制为 backend/.env。已有文件请直接编辑，不覆盖已有凭据。

```dotenv
OPENAI_API_KEY=填入你的服务商密钥
OPENAI_BASE_URL=https://api.openai-next.com/v1
MODEL=填入服务商提供的实际模型ID
```

不要将密钥发到聊天或提交 Git。Codex 开发使用 gpt-6.1-sol 与应用运行模型是两回事。更改配置后重启后端。API 地址已按负责人指定更新；模型支持工具调用与否须真实验证。

## 启动
```powershell
pwsh.exe -NoProfile -ExecutionPolicy Bypass -File .\start.ps1
```

打开 http://127.0.0.1:8000 。Ctrl+C 停止。脚本只启动一个本机后端进程并托管构建后的前端。

开发页面时另开终端：
```powershell
npm.cmd --prefix frontend run dev -- --host 127.0.0.1
```
访问 http://127.0.0.1:5173 ，API 转发到 8000。改页面后重新构建才会更新8000端口的静态页面。

## 演示路径
1. 工作台填入虚构示例经历和任意岗位 JD（也可上传 DOCX/文本 PDF/TXT/MD）。
2. 解析后核对姓名、教育、技能和每段经历；可直接修改。
3. 明确确认事实。再次编辑将撤销确认并清除旧生成结果。
4. 生成简历，核对模型输出，下载 Markdown。
5. 诊断、质检及面试题入口保留原有能力；不是完整的三题答题评分系统。

## 实施边界与明天待办
- 账户、用户隔离、任务历史、原始材料留存、正式记忆管理仍待实现。旧 profiles 接口是共享本机文件库，新工作台不读取该列表。
- 本轮先在负责人本机验证，服务绑定127.0.0.1，不是正式部署。
- Word/PDF 导出、图片输入、语音识别与合成待接入和实测。
- 数字检查只是提示，不能证明经历真实、不能证明所有陈述来源。事实由用户核对。
- 保留旧版页面以便复用；明天再分配材料生成、面试评分、解析导出等模块，不把未验证功能标成完成。
- 本轮代码按负责人授权提交到公开仓库；本地 `.env`、运行数据与真实用户材料不入库。

## 验证命令
```powershell
.\.venv\Scripts\python.exe tests/test_workbench_contract.py
.\.venv\Scripts\python.exe tests/smoke_server.py
npm.cmd --prefix frontend run build
```
接口手册：http://127.0.0.1:8000/docs 。健康检查：http://127.0.0.1:8000/api/health 。健康检查只证明服务可用和配置存在，不能证明真实模型调用成功。

## 本机验证记录（2026-10-30）
- 前端生产构建与 TypeScript 类型检查通过。
- 10 项后端 Mock 合约测试通过；服务启动、健康检查、前端静态托管和未知 API 的 JSON 404 冒烟检查通过。
- Edge 浏览器在 1440px 桌面与 390px 手机视口检查通过，无页面横向溢出；截图位于 data/ui-final-1440.png、data/ui-final-390.png。
- 浏览器使用合成材料与 Mock 响应验证：解析、编辑确认、生成、Markdown 下载；修改 JD 或事实会撤销确认并清除旧稿；生成期间锁定输入；HTTP 504 的 detail 错误可见且结束后恢复操作；未发现浏览器运行异常。
- 实际无密钥状态已验证：页面明确提示配置密钥，解析失败不伪装成功。随后用户配置密钥并重启，真实服务商解析、生成及工具调用均已验证，详见下方记录。
- 已读取服务商 quickstart 与 resources 指南：API 地址为 https://api.openai-next.com/v1，deepseek-v4-flash 列于服务商模型清单。清单不代表当前密钥权限或调用成功。
- 本轮保留本机服务运行，后台启动记录为 data/tonight-server.pid，输出日志为 data/tonight-server.out.log 和 data/tonight-server.err.log。关闭本次后台服务前先核对该 PID 的命令行为本项目 backend/main.py；后续使用 start.ps1 启动时按 Ctrl+C 停止。

## 真实服务商联调补充（2026-10-30）
- 模型 deepseek-v4-flash，使用虚构测试材料：真实解析成功，约 10.3 秒，返回未确认资料。
- 首轮真实生成暴露质检冲突：原始资料没有量化成果，但质检要求补数字，导致返回讨论文字。已修正为保留定性成果、缺量化仅提示人工补充；最后无工具轮次明确要求交付最终产物。
- 修正后真实生成成功，约 17.7 秒，输出以姓名标题开头的完整 Markdown 简历；实际调用 check_resume_quality 两次，high_remaining=0，未检测到新增数字。
- 11 项合约测试及超时控制测试通过，独立复审无新增阻断项。
- 真实生成记录与简历位于 data/live-generate-synthetic-v2.json、data/live-resume-synthetic-v2.md，仅使用虚构材料。生成文案仍需逐句核对；数字检查通过不等于所有事实均已证明。当前未对所有可能的非简历输出建立结构化拒绝机制，提示词不能保证每次产物形式。
- 本次重启后的日志按 data/server-时间.out.log 和 .err.log 保存，当前进程仍由 data/tonight-server.pid 记录。
