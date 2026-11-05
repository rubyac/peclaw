# 使用 GitHub Codespaces 试用

这是另一个由 GitHub 创建的开发环境，不是当前的 Codex 实例。Codespaces 提供浏览器可访问的 HTTPS 转发地址，默认私有，适合本人试用。可用性和费用取决于你的 GitHub 账户与剩余额度；停止不用的实例以避免继续消耗计算时间。

## 开始前

**本轮代码尚未提交/推送，远端最初只有 README。** 必须先把当前实现（含 `.devcontainer/`）提交并推送到 `rubyac/peclaw` 的目标分支；不能直接从未更新的 main 创建后期望看到应用。

仓库已加入 `.devcontainer/devcontainer.json` 与生命周期脚本。配置在当前环境通过 JSON、Compose、Origin 与 Cookie 设置检查，尚未创建真实 Codespace，不能宣称已拿到真实外部网址。

## 创建和打开

1. 在 GitHub 打开已更新的 `rubyac/peclaw` 分支。
2. 选择 **Code → Codespaces → Create codespace**，使用包含本轮代码的分支。
3. 等待容器工具、Docker 镜像构建及服务健康检查完成。
4. 在底部 **Ports** 面板打开 **3000 / PEClaw**。实际地址形如 `https://<codespace-name>-3000.app.github.dev/login`，具体以 GitHub 分配地址为准；这只是格式说明。
5. 在 Codespaces 终端（仓库根目录）开通自己的账号：

```sh
docker compose exec api python -m app.provision --email you@example.com --name "你的姓名" --organization "你的机构"
```

密码会交互式输入，不要放到命令参数、仓库或聊天中。然后在登录页输入自己的账号。

## 自动配置

首次创建由 postCreateCommand 生成仅本地的随机开发凭据并构建 API/Web。每次启动由 postStartCommand 等待 Docker，启动现有服务并检查就绪。脚本从 GitHub 的 CODESPACE_NAME 与 GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN 计算真实转发 Origin，传入 API/迁移/存储初始化三个容器，同时启用 Secure Cookie。

TLS 在 GitHub 转发入口终止，无需购买域名、另开 HTTPS 代理或手动填写 Origin。此方案**不使用** `deploy/compose.https.yml`，那份文件用于自有服务器。

重启服务、应用新增迁移时，使用生命周期脚本保留正确外部 Origin：

```sh
python3 scripts/codespaces_start.py
# 修改代码需要重建：
python3 scripts/codespaces_start.py --build-only
python3 scripts/codespaces_start.py
```

可用 `python3 scripts/codespaces_start.py --print-origin` 查看本实例地址。该脚本在当前 Codex 实例中会明确拒绝执行，不会凭空生成网址。不要只用普通 Compose 命令重建 API 而丢失动态 HTTPS Origin。

保留端口私有即可本人访问；访问链接时需要你的 GitHub 登录。想让别人试用应另行决定访问范围，不默认将项目公开。删除 Codespace 会删除其运行数据；真实资料应有独立备份，试用环境不作为长期存储。
