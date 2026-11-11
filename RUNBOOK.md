# 本机运行与验证

服务器部署参照 [DEPLOY.md](DEPLOY.md)。本机统一用根目录 `start.py` 启停：`start.py start` 起服务，同一个终端 Ctrl+C 或在另一个终端 `start.py stop` 关闭，不依赖手动记进程。

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

模型分两层，别混：

| 层 | 位置 | 管什么 |
| --- | --- | --- |
| 平台配置 | `backend/.env`（服务器为 `JOBAGENT_ENV_FILE`） | `/api/health` 的 `llm_configured`、脚本与测试用的默认端点 |
| 用户模型 | 页面「模型中心」，按账户加密存库 | 页面里的文本任务、图片解析、简历与 JD 生成 |

**页面业务请求只用当前账户（或访客）自己启用的模型**，没配置时接口返回 428，页面弹窗引导去「模型中心」，不会偷偷用平台 key 兜底。所以本机只要能在模型中心填好 Base URL、模型 ID 和 API Key 并「测试并启用」就能用；`backend/.env` 里的 `OPENAI_API_KEY` 不填也不影响页面功能。

文本模型和图片模型分开配置：截图导入、简历图片解析走**图片模型**，没配图片模型时同样返回 428 并提示先配置。

不要将密钥发到聊天或提交 Git。更改配置后重启后端。模型支持工具调用与否须真实验证。

如需平台默认端点（脚本、测试、健康字段），在 `backend/.env` 填写：

```dotenv
OPENAI_API_KEY=填入你的服务商密钥
OPENAI_BASE_URL=https://api.openai-next.com/v1
MODEL=填入服务商提供的实际模型ID
```

`backend/.env` 不存在时从 `backend/.env.example` 复制后编辑，已有文件不要覆盖。

## 本机个人模型加密密钥

若模型设置提示「个人模型加密服务未配置」，在项目根目录执行以下 PowerShell 命令，将输出的完整配置行粘贴到 `backend/.env`。若设置了 `JOBAGENT_ENV_FILE`，请改它指向的私有文件。已有空项时直接替换，保存后重启后端，再点击「测试并启用」。

```powershell
.\.venv\Scripts\python.exe -c "import base64,secrets; print('JOBAGENT_MODEL_ENCRYPTION_KEY=' + base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

此密钥用于加密保存个人模型配置。已有配置时应恢复原密钥，换新密钥会让已保存的个人模型配置无法解密。密钥只放在私有配置中，服务器操作见 [DEPLOY.md](DEPLOY.md)。

## 启动、停止与重启

`start.py` 启动前会检查 `frontend/dist/index.html`，没有构建产物直接退出。启动后进程号记在 `data/local-server.pid.json`，`stop` 读它来终止，所以停服务要用**同一个检出目录**的 `start.py stop`。

```powershell
# 前端有改动时先构建；只改后端或配置可跳过
npm.cmd --prefix frontend run build

# 启动（前台运行，占用当前终端）
.\.venv\Scripts\python.exe start.py start

# 另开终端关闭
.\.venv\Scripts\python.exe start.py stop
```

```sh
# Linux / macOS
npm --prefix frontend run build
.venv/bin/python start.py start
.venv/bin/python start.py stop
```

- 打开 http://127.0.0.1:8000 ，接口手册 http://127.0.0.1:8000/docs 。
- Windows 也可双击或执行 `start.bat` 启动、`start.bat stop` 关闭（只是上面两条命令的包装）。
- 前台运行时也可以直接 Ctrl+C 停止。若上次是强行结束的进程，PID 文件可能残留，先执行一次 `stop` 清理。
- 已经运行过一份时，`start` 会提示 `A JobAgent process is already recorded`，不会起第二个进程。
- 没记录时 `stop` 只打印 `No managed JobAgent process is recorded.`，不会报错。
- 不经过 `start.py`、直接运行 `backend/main.py` 起的服务，`start.py stop` 关不掉；先在原终端 Ctrl+C，否则端口被占用导致 `start` 失败。
- 端口用 `JOBAGENT_PORT` 覆盖（默认 8000），改端口后前端 dev server 的代理也会跟着走。

开发页面时另开终端（后端仍需先用上面的命令起）：

```powershell
npm.cmd --prefix frontend run dev -- --host 127.0.0.1
```

访问 http://127.0.0.1:5173 ，`/api` 转发到后端端口。改页面后只有重新构建才会更新 8000 端口的静态页面。

## 演示路径

1. 工作台按顶部四步导航依次操作：材料输入、确认事实、检查与优化、简历预览；可上传 DOCX、文本型 PDF、TXT、MD 或受支持的图片，也可直接填写事实。
2. 解析后核对姓名、教育、技能和每段经历，勾选事实确认，再点击“生成初稿并继续”。基础初稿无需岗位 JD，使用全部已确认经历，不推断岗位要求。
3. 在“检查与优化”填写或补充岗位要求，使用“简历检查”或“岗位匹配”。修改岗位要求保留当前稿和事实确认，旧报告失效；只有修改材料或真实事实才重新确认并清除旧稿。
4. 建议可逐条选择或全部采纳，应用后更新同一份 Markdown；也可手动编辑后再次检查。此循环没有固定次数，检查结果不强制阻止预览，建议应用失败保留原稿。满意后点击“查看最终简历”，人工核对并导出。
5. 目标岗位、已确认事实和当前简历齐备后，点击“准备模拟面试”。面试行为和历史兼容边界以 [面试行为契约](frontend/src/pages/interview/BEHAVIOR.md) 为准；语音交互仍待接入。
6. 左侧「岗位收件箱」用于收集 JD：粘贴文本或从截图导入后会先回填表单，核对保存才入库；「用这份 JD 去匹配」把正文带进工作台。

## 本机重启

从仓库根目录运行。只改私有配置时可跳过前端构建。

```powershell
git log -1 --oneline
npm.cmd --prefix frontend run build
.\.venv\Scripts\python.exe start.py stop
.\.venv\Scripts\python.exe start.py start
```

重启后确认浏览器加载的是新构建：页面引用的 `frontend/dist/assets/index-*.js` 文件名 hash 应该变了，普通刷新可能命中旧缓存，必要时 Ctrl+F5。

## 验证命令

```powershell
# 后端（按影响范围挑）
.\.venv\Scripts\python.exe -m unittest tests.test_jobs_api tests.test_paste tests.test_documents tests.test_sources

# 全量回归（既有的长期失败项见 docs/HANDOFF.md 第六节，别当成自己弄坏）
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"

# 冒烟：自己起临时服务（8123 端口）检查健康接口与 SPA 兜底
.\.venv\Scripts\python.exe tests/smoke_server.py

# 前端
npm.cmd --prefix frontend run build
npm.cmd --prefix frontend exec vitest run
```

健康检查 `http://127.0.0.1:8000/api/health` 只证明服务可用、平台配置存在，不能证明某个账户的模型可用，也不能替代真实模型验收。
