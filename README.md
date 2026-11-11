# 职得 offer

职得 offer 是一个求职 AI Agent。项目使用 React、TypeScript、FastAPI 和 SQLite。

- **免注册体验**：使用独立临时会话体验完整工作台、简历导出和模拟面试。
- **简历工作台**：录入材料、确认事实、生成基础稿，按岗位检查和优化，再导出 Markdown、Word 或 PDF。
- **经历库**：维护经历卡片，支持查重、合并和版本恢复。
- **岗位收件箱**：粘贴 JD 或从截图导入，本地识别字段并确认后入库；管理员可按省启用公告信源并人工一键采集。
- **面经与内推**：匿名投稿面经/内推/JD 评价，入库前自动脱敏，管理员审核通过后公开；支持有帮助与举报。
- **模拟面试**：可生成题库或直接开始文字面试，结束后查看反馈和历史。
- **账户与个人模型**：用户名和密码注册登录，个人模型密钥在服务端加密保存。

## 运行与开发

本机启停统一用根目录 `start.py`（启动前需先构建前端）：

```powershell
npm.cmd --prefix frontend run build
.\.venv\Scripts\python.exe start.py start
.\.venv\Scripts\python.exe start.py stop
```

打开 http://127.0.0.1:8000 。完整的安装、模型配置、重启与验证步骤见 [RUNBOOK.md](RUNBOOK.md)；服务器部署、systemd 启停和环境变量见 [DEPLOY.md](DEPLOY.md)；迭代和提交规范见 [AGENTS.md](AGENTS.md)。

## 功能契约

- [账户和个人模型](ACCOUNT.md)
- [简历工作台](frontend/src/pages/workbench/BEHAVIOR.md)
- [个人经历库](LIBRARY.md)
- [岗位收件箱与资料层](docs/plan-jobs-knowledge-community.md)
- [社群与审核](docs/COMMUNITY.md)
- [模拟面试](frontend/src/pages/interview/BEHAVIOR.md)
- [自动保存与历史](PERSISTENCE.md)
- [模型错误](MODEL_ERRORS.md)
