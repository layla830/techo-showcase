# 独立部署示例

`techo.example.com`、`/srv/techo` 和服务用户 `techo` 均为示例值，请替换为自己的配置。

1. 为新实例准备独立目录、系统用户、数据库、域名及随机凭据。
2. 使用 Python 3.12 创建项目虚拟环境，安装锁定依赖。创建仅服务用户可写的 `data/`；根 `.env` 只供该用户读取。
3. 用项目自带命令生成 Argon2 密码哈希，并生成独立随机 Agent token，填入 `.env`。`TECHO_PUBLIC_ORIGIN` 必须是你自己的 HTTPS origin，不含路径；`TECHO_TIMEZONE` 可选，默认 `Asia/Shanghai`。
4. 根据自己的路径和空闲端口调整 `deploy/techo.service`、`deploy/nginx.conf`；这些文件不是自动安装程序。
5. 后端保留 `/techo/` 前缀，反向代理的 `proxy_pass` 不追加尾斜杠。浏览器会话使用 Secure cookie，需要 HTTPS。
6. 独立实例启动后，检查健康接口、未登录 API 的 401、浏览器登录和 Agent API，再开展功能验收。

回退时停止实例、保留当前目录和数据，并恢复变更前保存的源码与配置。
