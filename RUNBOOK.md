# 运行与部署（本机 + 服务器）

同一个仓库、同一套代码，只是环境不同：**本机用 `start.py` 管理进程，服务器用 systemd**。
配置读取顺序、环境变量、验证命令两边通用，差异都在具体小节里标出来了。

## 两种环境对照

| 项目 | 本机（Windows / macOS / Linux 开发） | 服务器（Linux + systemd） |
| --- | --- | --- |
| 启停 | `.venv/bin/python start.py start` / `stop` | `systemctl start/stop/restart jobagent` |
| 配置位置 | `backend/.env` | 默认同左；也可用 `JOBAGENT_ENV_FILE` 指向外部文件 |
| 端口 | `JOBAGENT_PORT`（默认 8000） | 同左，需与 Nginx `proxy_pass` 一致 |
| 前端 | `npm --prefix frontend run build` 后用 8000 访问 | 同左，构建产物由后端托管 |
| 数据库 | `data/accounts.sqlite3` | 同左，更新前必须停服务备份 `data/` |
| 管理员 | `manage.py admin create 用户名` | 同左（本机/服务器都在服务器终端跑） |

**管理员只能由运维创建**：公开注册的账号一律是普通用户，只能进用户端；
管理端是独立入口 `/admin`（见下文「管理员与两个入口」）。

---

## 本机运行

本机用根目录 `start.py` 启停：`start.py start` 起服务，同一个终端 Ctrl+C 或在另一个终端 `start.py stop` 关闭，不依赖手动记进程。

### 环境准备

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

### 模型配置

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

### 本机个人模型加密密钥

若模型设置提示「个人模型加密服务未配置」，在项目根目录执行以下 PowerShell 命令，将输出的完整配置行粘贴到 `backend/.env`。若设置了 `JOBAGENT_ENV_FILE`，请改它指向的私有文件。已有空项时直接替换，保存后重启后端，再点击「测试并启用」。

```powershell
.\.venv\Scripts\python.exe -c "import base64,secrets; print('JOBAGENT_MODEL_ENCRYPTION_KEY=' + base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

此密钥用于加密保存个人模型配置。已有配置时应恢复原密钥，换新密钥会让已保存的个人模型配置无法解密。密钥只放在私有配置中；服务器上的同一操作见「服务器部署 → 个人模型加密配置」。

### 启动、停止与重启

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

### 演示路径

1. 工作台按顶部四步导航依次操作：材料输入、确认事实、检查与优化、简历预览；可上传 DOCX、文本型 PDF、TXT、MD 或受支持的图片，也可直接填写事实。
2. 解析后核对姓名、教育、技能和每段经历，勾选事实确认，再点击“生成初稿并继续”。基础初稿无需岗位 JD，使用全部已确认经历，不推断岗位要求。
3. 在“检查与优化”填写或补充岗位要求，使用“简历检查”或“岗位匹配”。修改岗位要求保留当前稿和事实确认，旧报告失效；只有修改材料或真实事实才重新确认并清除旧稿。
4. 建议可逐条选择或全部采纳，应用后更新同一份 Markdown；也可手动编辑后再次检查。此循环没有固定次数，检查结果不强制阻止预览，建议应用失败保留原稿。满意后点击“查看最终简历”，人工核对并导出。
5. 目标岗位、已确认事实和当前简历齐备后，点击“准备模拟面试”。面试行为和历史兼容边界以 [面试行为契约](frontend/src/pages/interview/BEHAVIOR.md) 为准；语音交互仍待接入。
6. 左侧「岗位收件箱」用于收集 JD：粘贴文本或从截图导入后会先回填表单，核对保存才入库；「用这份 JD 去匹配」把正文带进工作台。
7. 左侧「面经与内推」：浏览已审核匿名卡片，或在「投稿 / 我的」写复盘提交审核；管理员多一个「审核」页签，可以看正文、通过或写理由退回。

### 管理员与两个入口（管理端 / 用户端）

站点分成两个入口，普通人只能进用户端：

| 入口 | 地址 | 谁能进 |
| --- | --- | --- |
| 用户端 | `/` | 所有注册用户与免注册试用（求职功能：工作台、经历库、简历库、岗位收件箱、面经与内推、模型中心） |
| 管理端 | `/admin` | 只有管理员。未登录显示管理员登录页；普通账号登录后显示"仅管理员可访问" |

**管理员只能由运维创建**，公开注册不会产生管理员（谁先注册谁是管理员不合理）：

```powershell
# 直接创建管理员（推荐）：账号不存在时新建，随机密码只打印一次
.\.venv\Scripts\python.exe backend/manage.py admin create zhangsan

# 或给已注册的账号授权
.\.venv\Scripts\python.exe backend/manage.py admin grant zhangsan

# 查看 / 回收
.\.venv\Scripts\python.exe backend/manage.py admin list
.\.venv\Scripts\python.exe backend/manage.py admin revoke zhangsan
```

服务端启动时如果一个管理员都没有，日志会打印这条创建命令，避免部署时忘配而卡死。
撤销有保护：不允许撤销最后一个管理员。管理员角色存 `user_roles`，随账户 SQLite 一起备份。
进出管理端都在 `/admin`，用户端不再显示任何管理员入口。

### 本机重启

从仓库根目录运行。只改私有配置时可跳过前端构建。

```powershell
git log -1 --oneline
npm.cmd --prefix frontend run build
.\.venv\Scripts\python.exe start.py stop
.\.venv\Scripts\python.exe start.py start
```

重启后确认浏览器加载的是新构建：页面引用的 `frontend/dist/assets/index-*.js` 文件名 hash 应该变了，普通刷新可能命中旧缓存，必要时 Ctrl+F5。

### 验证命令

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

---

## 服务器部署（Linux）

适用于 Python 3.12、Node.js 22、Nginx 与 systemd 的服务器。当前未连接服务器执行部署；其他平台需按实际环境调整。浏览器通过同一域名访问页面和 `/api`，密钥只由后端读取。

### 配置契约

- 配置默认读项目里的 `backend/.env`（服务单元 `WorkingDirectory=/opt/jobagent`，因此实际是 `/opt/jobagent/backend/.env`），文件名沿用本机习惯，部署时直接复制 `backend/.env.example` 填写即可。
- 想把配置放到仓库目录之外时，在 systemd 单元里设 `JOBAGENT_ENV_FILE=/etc/jobagent/jobagent.env`（或在该 shell 里导出），并把 `deploy/jobagent.env.example` 复制过去填写。**一旦设了 `JOBAGENT_ENV_FILE`，文件不存在或不可读就是启动失败，不回退到 `.env`**；没设时才按 `backend/.env` → 当前目录 `.env` → 项目根 `.env` 的顺序查找。
- 两种方式都不要把真实密钥写进 Python、前端源码或 Git 跟踪文件；仓库只提供 `backend/.env.example` 与 `deploy/jobagent.env.example` 两个无密钥模版。进程环境变量优先于文件。
- `JOBAGENT_HOST` 默认 `127.0.0.1`，Nginx 转发到该地址；`JOBAGENT_PORT` 必须在 1–65535 内。单进程运行，数据仍保存到项目 `data/`，更新代码时必须保留并备份整个目录。
- Nginx 传递 HTTPS 协议头，后端仅信任本机代理。HTTPS 登录 Cookie 会带 Secure。生产访问前应通过服务器已有的证书管理方式配置 HTTPS。
- 模型健康字段只证明配置存在；真实文本、图片和工具调用能力需单独验收。PDF 导出需可用的中文 TrueType 字体，用 `JOBAGENT_PDF_FONT` 指定服务器实际路径。
- **平台配置不等于用户模型**：页面里的文本任务与图片解析只用每个账户（或访客会话）在「模型中心」自己启用的模型，未配置时返回 428 并引导去配置，不用平台 key 兜底。平台配置负责健康字段、脚本与测试的默认端点。

### 环境变量清单

全部写在配置文件里（默认 `backend/.env`，或 `JOBAGENT_ENV_FILE` 指向的文件）；进程环境变量优先。

| 变量 | 默认 | 作用 |
| --- | --- | --- |
| `JOBAGENT_ENV_FILE` | 无 | 指定私有配置文件；显式指定但缺失或不可读时启动失败 |
| `JOBAGENT_HOST` / `JOBAGENT_PORT` | `127.0.0.1` / `8000` | 监听地址与端口，须与 Nginx `proxy_pass` 一致 |
| `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `MODEL` | 空 / 厂商地址 / 内置默认 | 平台默认端点，供脚本、测试与健康字段使用，不参与页面业务请求 |
| `JOBAGENT_FALLBACKS` | 空 | 平台端点备用链（逗号分隔），仅在上面这层生效 |
| `JOBAGENT_MODEL_ENCRYPTION_KEY` | 无 | 加密个人模型 API Key 的独立密钥，见下文；缺失时用户无法保存个人模型 |
| `JOBAGENT_CUSTOM_MODEL_BASE_URLS` | 空 | 允许用户填写的自定义 HTTPS Base URL 白名单，逗号分隔 |
| `JOBAGENT_ADMIN_USERNAMES` | 空 | 仅首次迁移用：把这些已注册用户名提升为管理员，之后以数据库 `user_roles` 为准 |
| `JOBAGENT_PDF_FONT` | 自动查找常见中文字体 | 导出 PDF 用的中文 TrueType 字体绝对路径；找不到任何字体时导出返回 503 |
| `JOBAGENT_LLM_DEADLINE` / `JOBAGENT_FLOW_DEADLINE` | 100 / 150 秒 | 单次模型调用 / 整条流程的时间预算 |
| `JOBAGENT_TOKEN_BUDGET` | 0 | 进程 token 预算上限，0 表示只计量不限制 |
| `JOBAGENT_TOOL_ROUNDS` / `JOBAGENT_MAX_EXPERIENCES` | 3 / 4 | 工具循环轮数、生成时保留的经历条数上限 |
| `JOBAGENT_EVENTS_PATH` | `data/events.jsonl` | 事件流写入位置，可能含材料内容，不要提交 Git |

联系 QQ 不在环境变量里：用管理员账号登录后在「管理后台 → 联系方式」填写，存在账户数据库。

### 首次安装

以下以代码目录 `/opt/jobagent`、服务账户 `jobagent` 为例；先准备这些目录和账户，安装 Python 3.12、Node.js 22、Nginx，代码和 `data/` 必须允许该账户读写。不要把本机真实用户数据上传到演示服务器。

在代码目录执行：

```sh
git log -1 --oneline
python3.12 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
npm --prefix frontend ci
npm --prefix frontend run build
```

首次创建配置。默认方式（与本机一致，推荐先这样做）：

```sh
cd /opt/jobagent
test ! -e backend/.env && cp backend/.env.example backend/.env
chmod 600 backend/.env && chown jobagent:jobagent backend/.env
$EDITOR backend/.env
```

可选加固（配置不放在代码目录）：

```sh
sudo install -d -m 750 -o root -g jobagent /etc/jobagent
sudo test ! -e /etc/jobagent/jobagent.env && sudo install -m 640 -o root -g jobagent deploy/jobagent.env.example /etc/jobagent/jobagent.env
sudoedit /etc/jobagent/jobagent.env
```

然后取消 `deploy/jobagent.service` 里 `Environment=JOBAGENT_ENV_FILE=...` 的注释再安装服务单元。两者不共存：设了 `JOBAGENT_ENV_FILE` 后就**不再读** `backend/.env`。

必填两项：

- `JOBAGENT_MODEL_ENCRYPTION_KEY`：加密保存用户个人模型 API Key 的独立密钥（见下文「个人模型加密配置」）。不填时注册用户无法保存自己的模型配置，页面一直提示去配置。
- `JOBAGENT_PORT` / `JOBAGENT_HOST`：必须与 Nginx `proxy_pass` 一致，默认 `127.0.0.1:8000`。

选填：`OPENAI_API_KEY`、`OPENAI_BASE_URL`、`MODEL` 是平台默认端点，只影响健康字段、脚本和测试（页面业务请求用各账户自己启用的模型）；`JOBAGENT_PDF_FONT` 为导出 PDF 的中文 TrueType 字体绝对路径；`JOBAGENT_CUSTOM_MODEL_BASE_URLS` 为允许用户填写的自定义 HTTPS 端点白名单。值包含特殊字符时用单引号包围；不要把配置当 Shell 脚本执行。服务账户需能读取配置和字体。

检查 `deploy/jobagent.service` 的账户和绝对路径。端口由服务器配置中的 `JOBAGENT_PORT` 管理；修改时须同步 Nginx 的 `proxy_pass` 和下方健康检查地址。将服务文件安装为 `/etc/systemd/system/jobagent.service`；若目标已存在，先备份和核对差异再替换。执行：

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now jobagent
sudo systemctl status jobagent --no-pager
curl --fail http://127.0.0.1:8000/api/health
curl --fail -o /dev/null http://127.0.0.1:8000/
```

首次登录后先到「模型中心」配置自己的文本模型和图片模型；管理员账号也要各自配置，服务端不会替用户保存共享 key，也不会用平台 key 兜底。

### 运行、停止与重启

服务器上用 systemd 托管，**不要用 `start.py`**（它是本机 PID 托管，会与 systemd 抢进程）。服务单元直接运行 `backend/main.py`：

```sh
sudo systemctl start jobagent      # 启动
sudo systemctl stop jobagent       # 关闭（先停服务再备份 data/）
sudo systemctl restart jobagent    # 改代码或配置后重启
sudo systemctl status jobagent --no-pager
sudo systemctl disable jobagent    # 取消开机自启（临时下线）
```

查看启动失败原因：`sudo journalctl -u jobagent -n 80 --no-pager`。回传日志前删除密钥和个人资料。修改任何环境变量、模型加密密钥、字体路径后都必须 `restart`，只 reload Nginx 不生效。

### 对外访问

按 `deploy/nginx.conf.example` 新建站点，将 `server_name` 改成实际域名并启用；已有配置先备份。该文件提供 HTTP 反向代理基础，公开使用前配置 HTTPS。检查通过后重载：

```sh
sudo nginx -t
sudo systemctl reload nginx
```

在浏览器中用实际域名检查：注册/登录、刷新恢复、解析虚构材料、确认事实、生成简历、面试、Word/PDF 导出。模型失败应可见，不得只凭健康检查认定全部可用。不要开放后端 8000 端口到公网。

### 更新与排障

更新前备份服务器配置、当前提交及 `data/`。SQLite 应在**停止服务后**整体备份，避免遗漏事务文件：

```sh
sudo systemctl stop jobagent
sudo tar -czf ~/jobagent-data-$(date +%F).tar.gz -C /opt/jobagent data
sudo systemctl start jobagent
```

保持代码目录与服务路径一致，拉取后重新构建并重启：

```sh
git pull --ff-only origin main
git log -1 --oneline
.venv/bin/python -m pip install -r backend/requirements.txt
npm --prefix frontend ci
npm --prefix frontend run build
sudo systemctl restart jobagent
curl --fail http://127.0.0.1:8000/api/health
curl --fail -o /dev/null http://127.0.0.1:8000/
```

配置变更同样需要 `sudo systemctl restart jobagent`。启动失败查看 `sudo journalctl -u jobagent -n 80 --no-pager`，回传前删除密钥和个人资料。Nginx 超时需至少覆盖应用的 150 秒流程预算；模板设置 180 秒，与前端请求超时一致。

### 个人模型加密配置

首次部署时，在服务器终端生成一把独立的 32 字节随机密钥。命令输出完整配置行。

```sh
.venv/bin/python -c "import base64,secrets; print('JOBAGENT_MODEL_ENCRYPTION_KEY=' + base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

将输出粘贴到 `JOBAGENT_ENV_FILE` 指向的服务器私有配置文件，再执行 `sudo systemctl restart jobagent`。在模型设置中点击「测试并启用」验证。真实密钥不得提交到 Git。

所有实例使用同一个值，重启和升级时保留它。数据库备份与密钥分开保管。已有个人模型配置时，优先恢复原密钥，生成新密钥会导致已有配置无法解密。若原密钥丢失，用户须重新填写模型 API Key。未配置有效密钥时，注册用户无法保存个人模型配置。

网站管理员账号仅有统计权限。数据库单独泄露时，API Key 字段是密文。控制后端进程或同时持有数据库与加密密钥的运营者仍能取得用户密钥。

### 服务器上的管理员

与「管理员与两个入口」一节一致：用 `backend/manage.py admin create` 或在
「管理端 → 管理员角色」里授予。服务器上执行时把路径换成本机的
`.venv/bin/python backend/manage.py ...`，其余相同。**管理端地址是 `/admin`**，
Nginx 不需要单独配置（同一域名下的 SPA 路由）。

### 联系管理员

用管理员账号打开「管理后台 → 联系方式」，填写愿意公开的 QQ 号并保存。工作台右上角会显示「联系管理员」。留空保存即可隐藏入口。号码随账户 SQLite 数据库保存，修改后立即生效。
