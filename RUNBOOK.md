# 本机运行与验证

服务器部署参照 [DEPLOY.md](DEPLOY.md)。

## 环境准备
需要 Python 3.12+ 和 Node.js 22+。以下是 Windows 命令。不要把 WindowsApps 的 Python 别名当成已安装的解释器。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
npm.cmd --prefix frontend ci
npm.cmd --prefix frontend run build
```

Linux / macOS 首次运行：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
npm --prefix frontend ci
npm --prefix frontend run build
```

已有项目 .venv 时无需重建。

## 模型配置
若 backend/.env 不存在，将 backend/.env.example 复制为 backend/.env。已有文件请直接编辑，不覆盖已有凭据。

```dotenv
OPENAI_API_KEY=填入你的服务商密钥
OPENAI_BASE_URL=https://api.openai-next.com/v1
MODEL=填入服务商提供的实际模型ID
```

不要将密钥发到聊天或提交 Git。更改配置后重启后端。模型支持工具调用与否须真实验证。

## 启动
```powershell
# Windows
.\.venv\Scripts\python.exe start.py
```

```sh
# Linux / macOS
.venv/bin/python start.py
```

打开 http://127.0.0.1:8000 。Ctrl+C 停止。脚本只启动一个本机后端进程并托管构建后的前端。

开发页面时另开终端：
```powershell
npm.cmd --prefix frontend run dev -- --host 127.0.0.1
```
访问 http://127.0.0.1:5173 ，API 转发到 8000。改页面后重新构建才会更新8000端口的静态页面。

## 演示路径
1. 工作台按顶部四步导航依次操作：材料输入、确认事实、检查与优化、简历预览；可上传 DOCX/文本 PDF/TXT/MD 或受支持的图片，也可直接填写事实。
2. 解析后核对姓名、教育、技能和每段经历，勾选事实确认，再点击“生成初稿并继续”。基础初稿无需岗位 JD，使用全部已确认经历，不推断岗位要求。
3. 在“检查与优化”填写或补充岗位要求，使用“简历检查”或“岗位匹配”。修改岗位要求保留当前稿和事实确认，旧报告失效；只有修改材料或真实事实才重新确认并清除旧稿。
4. 建议可逐条选择或全部采纳，应用后更新同一份 Markdown；也可手动编辑后再次检查。此循环没有固定次数，检查结果不强制阻止预览，建议应用失败保留原稿。满意后点击“查看最终简历”，人工核对并导出。
5. 目标岗位、已确认事实和当前简历齐备后，点击“准备模拟面试”。面试行为和历史兼容边界以 [面试行为契约](frontend/src/pages/interview/BEHAVIOR.md) 为准；语音交互仍待接入。

## 本机重启

从仓库根目录运行。只改私有配置时可跳过前端构建。

```powershell
git log -1 --oneline
npm.cmd --prefix frontend run build
.\.venv\Scripts\python.exe start.py stop
.\.venv\Scripts\python.exe start.py start
```

直接运行 `backend/main.py` 启动的服务，需先在原启动终端按 Ctrl+C 停止，再启动。

## 验证命令
```powershell
.\.venv\Scripts\python.exe tests/test_workbench_contract.py
.\.venv\Scripts\python.exe tests/smoke_server.py
npm.cmd --prefix frontend run build
```
接口手册：http://127.0.0.1:8000/docs 。健康检查：http://127.0.0.1:8000/api/health 。健康检查只证明服务可用和配置存在，不能证明真实模型调用成功。
