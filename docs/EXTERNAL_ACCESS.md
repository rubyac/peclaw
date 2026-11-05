# 外部访问与 HTTPS 部署

当前开发实例属于 Codex 托管云环境，GitHub 提供仓库托管。实例没有可用的公网入站端口配置工具或已分配域名。只启动容器、绑定 0.0.0.0、发布 Codex 环境快照或修改出站域名白名单，都不会自动生成外部可访问的网站。

仓库提供 Docker 主机的 HTTPS 部署覆盖配置 `deploy/compose.https.yml`。这份配置已通过 Compose 合并检查，**尚未在外部主机部署，也没有已分配的访问网址**。

## 需要的部署目标

- 能运行 Docker Engine/Compose 的服务器，拥有管理权限。
- 一个指向该服务器的域名，外部 TCP 80/443 可达。
- 服务器可访问所需镜像/依赖源，以及证书签发服务。
- 当前开发代码尚未推送到 GitHub；从 GitHub 部署前必须先提交并推送所需代码，不能直接用只有 README 的远端版本部署。

不需要在聊天中提供任何密码或私钥。服务器访问应通过平台安全连接/密钥配置提供。

## 部署命令

将包含本轮实现的完整仓库放在目标服务器，在仓库根目录执行：

```sh
python3 scripts/init_env.py
# 在目标服务器自己的 .env 中追加域名，例如：
# PUBLIC_DOMAIN=research.your-domain.com
# 示例域名只是占位符，不能作为现成访问入口。
docker compose -f docker-compose.yml -f deploy/compose.https.yml build api web
docker compose -f docker-compose.yml -f deploy/compose.https.yml up -d --wait
docker compose exec api python -m app.provision --email you@example.com --name "你的姓名" --organization "你的机构"
```

输入账号密码后，用 `https://<你的域名>/login` 登录。不要把密码写入命令行参数。Caddy 在真实域名和网络条件具备时自动签发和续期证书；证书数据保留在 caddy_data 卷。首次证书签发需要外部网络，Compose 配置通过不等于签发或外部连通已成功。

覆盖文件会给 API、迁移和存储初始化三个进程同时设置 production、Secure Cookie 与精确 HTTPS Origin，避免使用本地 HTTP 配置而导致登录失败。应用的 API、数据库、Redis 与对象存储继续只映射主机回环端口；外部仅开放 HTTPS Web 入口。

如果部署目标也是 Codex 当前受限开发实例，以上配置不会突破实例的入站网络边界，仍需要平台提供访问能力；此文件主要供外部 Docker 主机使用。

## 检查与停止

```sh
docker compose -f docker-compose.yml -f deploy/compose.https.yml config --quiet
docker compose -f docker-compose.yml -f deploy/compose.https.yml ps
docker compose -f docker-compose.yml -f deploy/compose.https.yml logs --tail=100 proxy
# 停止时保留所有数据卷：
docker compose -f docker-compose.yml -f deploy/compose.https.yml down
```

完成部署后还需从外部验证页面、登录 Cookie/Origin、项目访问、证书与重启恢复。此配置用于初期试用，不替代生产验收；现有 RustFS alpha、开发数据库角色与备份运维的限制见 SECURITY.md 和 OPERATIONS.md。
