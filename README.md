# 职得 offer

职得 offer 是一个求职 AI Agent。项目使用 React、TypeScript、FastAPI 和 SQLite。

- **免注册体验**：使用独立临时会话体验完整工作台、简历导出和模拟面试。
- **简历工作台**：录入材料、确认事实、生成基础稿，按岗位检查和优化，再导出 Markdown、Word 或 PDF。
- **经历库**：维护经历卡片，支持查重、合并和版本恢复。
- **模拟面试**：可生成题库或直接开始文字面试，结束后查看反馈和历史。
- **账户与个人模型**：用户名和密码注册登录，个人模型密钥在服务端加密保存。

## 运行与开发

- [本机启动、重启与验收](RUNBOOK.md)
- [服务器部署与运行配置](DEPLOY.md)
- [迭代和提交规范](AGENTS.md)

## 功能契约

- [账户和个人模型](ACCOUNT.md)
- [简历工作台](frontend/src/pages/workbench/BEHAVIOR.md)
- [个人经历库](LIBRARY.md)
- [模拟面试](frontend/src/pages/interview/BEHAVIOR.md)
- [自动保存与历史](PERSISTENCE.md)
- [模型错误](MODEL_ERRORS.md)
