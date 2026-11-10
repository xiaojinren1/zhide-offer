# Linux 服务器部署

适用于 Python 3.12、Node.js 22、Nginx 与 systemd 的服务器。当前未连接服务器执行部署；其他平台需按实际环境调整。浏览器通过同一域名访问页面和 `/api`，密钥只由后端读取。

## 配置契约

- 真实配置保存为 `/etc/jobagent/jobagent.env`，不要写入 Python、前端源码或 Git 跟踪文件。仓库仅提供 `deploy/jobagent.env.example`。
- systemd 使用 `JOBAGENT_ENV_FILE` 指定该文件。显式指定文件不存在或不可读时启动失败，不回退本机配置；未指定时保留原有 `.env` 查找顺序。进程环境变量优先，修改后必须重启服务。
- `JOBAGENT_HOST` 默认 `127.0.0.1`，Nginx 转发到该地址；`JOBAGENT_PORT` 必须在 1–65535 内。单进程运行，数据仍保存到项目 `data/`，更新代码时必须保留并备份整个目录。
- Nginx 传递 HTTPS 协议头，后端仅信任本机代理。HTTPS 登录 Cookie 会带 Secure。生产访问前应通过服务器已有的证书管理方式配置 HTTPS。
- 模型健康字段只证明配置存在；真实文本、图片和工具调用能力需单独验收。PDF 导出需可用的中文 TrueType 字体，用 `JOBAGENT_PDF_FONT` 指定服务器实际路径。

## 首次安装

以下以代码目录 `/opt/jobagent`、服务账户 `jobagent` 为例；先准备这些目录和账户，安装 Python 3.12、Node.js 22、Nginx，代码和 `data/` 必须允许该账户读写。不要把本机真实用户数据上传到演示服务器。

在代码目录执行：

```sh
git log -1 --oneline
python3.12 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
npm --prefix frontend ci
npm --prefix frontend run build
```

首次创建配置（已有文件时停止，不覆盖）：

```sh
sudo install -d -m 750 -o root -g jobagent /etc/jobagent
sudo test ! -e /etc/jobagent/jobagent.env && sudo install -m 640 -o root -g jobagent deploy/jobagent.env.example /etc/jobagent/jobagent.env
sudoedit /etc/jobagent/jobagent.env
```

填写 `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`MODEL`，需要 PDF 时填写字体路径。值包含特殊字符时用单引号包围；不要把配置当 Shell 脚本执行。服务账户需能读取配置和字体。

检查 `deploy/jobagent.service` 的账户和绝对路径。端口由服务器配置中的 `JOBAGENT_PORT` 管理；修改时须同步 Nginx 的 `proxy_pass` 和下方健康检查地址。将服务文件安装为 `/etc/systemd/system/jobagent.service`；若目标已存在，先备份和核对差异再替换。执行：

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now jobagent
sudo systemctl status jobagent --no-pager
curl --fail http://127.0.0.1:8000/api/health
curl --fail -o /dev/null http://127.0.0.1:8000/
```

## 对外访问

按 `deploy/nginx.conf.example` 新建站点，将 `server_name` 改成实际域名并启用；已有配置先备份。该文件提供 HTTP 反向代理基础，公开使用前配置 HTTPS。检查通过后重载：

```sh
sudo nginx -t
sudo systemctl reload nginx
```

在浏览器中用实际域名检查：注册/登录、刷新恢复、解析虚构材料、确认事实、生成简历、面试、Word/PDF 导出。模型失败应可见，不得只凭健康检查认定全部可用。不要开放后端 8000 端口到公网。

## 更新与排障

更新前备份服务器配置、当前提交及 `data/`（SQLite 应停服务后备份整个目录，避免遗漏事务文件）。保持代码目录与服务路径一致，拉取后重新构建并重启：

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

## 个人模型加密配置

首次部署时，在服务器终端生成一把独立的 32 字节随机密钥。命令输出完整配置行。

```sh
.venv/bin/python -c "import base64,secrets; print('JOBAGENT_MODEL_ENCRYPTION_KEY=' + base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

将输出粘贴到 `JOBAGENT_ENV_FILE` 指向的服务器私有配置文件，再执行 `sudo systemctl restart jobagent`。在模型设置中点击「测试并启用」验证。真实密钥不得提交到 Git。

所有实例使用同一个值，重启和升级时保留它。数据库备份与密钥分开保管。已有个人模型配置时，优先恢复原密钥，生成新密钥会导致已有配置无法解密。若原密钥丢失，用户须重新填写模型 API Key。未配置有效密钥时，注册用户无法保存个人模型配置。

网站管理员账号仅有统计权限。数据库单独泄露时，API Key 字段是密文。控制后端进程或同时持有数据库与加密密钥的运营者仍能取得用户密钥。

## 管理员角色

先注册并确认首个管理员账号由你控制，再把用户名填入 JOBAGENT_ADMIN_USERNAMES 并重启后端。用该账号登录并打开管理后台，已有正式账号会一次性迁移到数据库。确认左侧出现「管理后台」后，可移除环境变量。后续在「管理后台 → 管理员角色」授予或撤销其他账号的权限。角色保存在账户 SQLite 中，随数据库一起备份。
