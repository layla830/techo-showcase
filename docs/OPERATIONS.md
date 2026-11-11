# 数据与维护

## 本地数据

条目和会话位于 `data/techo.db`，照片位于 `data/photos/`。`.env`、`data/`、个人 `seed.json`、备份及运行日志均留在自己的环境中，不提交至源码仓库。

## 备份

在自己的实例根目录运行 `.venv/bin/python tools/backup.py /var/backups/techo`。该路径只是示例，应先建立合适的权限和保留策略。工具使用 SQLite backup API，不能用复制一个正在写入的 WAL 数据库文件代替一致性备份。备份包含私人记录与会话，应与公开源码分开保管。

## Agent 客户端

`tools/techo_client.py` 从自己项目的 `.env` 或指定环境读取凭据。`TECHO_BASE_URL` 不含 `/api/v1`；只支持 HTTPS，或严格限定的 loopback HTTP。不要把 token 写入 URL、命令行或日志。

## 更新与恢复

修改前记录自己实例的版本并完成可恢复备份。修改后先在独立测试环境验证。恢复时先停止该实例，并将旧数据与新数据分别保存，不混合数据库及 WAL 文件。
