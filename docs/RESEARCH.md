# 设计参考与取舍

以下为架构与设计参考。引用不表示复制业务代码或素材，也不改变相应项目的许可。

| 参考 | 已核实技术与许可 | techo 采用的设计经验 | 取舍 |
| --- | --- | --- | --- |
| [shared-page](https://github.com/KKarsyline/shared-page) | FastAPI、aiosqlite、SwiftUI；PolyForm Noncommercial 1.0.0 | 两个写者共享日历；操作者由服务端确定；业务变更附快照；seed 稳定实例 | 其核心文件集成了存储、渲染和工具分发；无浏览器会话、四资源或原子 batch，不能直接当本项目后端。图片和贴纸结构保存在 iOS 本地。 |
| [flatnotes](https://github.com/dullage/flatnotes) | FastAPI、Markdown/Whoosh、Vue；MIT | DTO、认证依赖、存储边界、同一应用提供静态页面 | 存储不是 SQLite，删除是物理删除；不能沿用其标题作为资源标识的模型。 |
| [Memos](https://github.com/usememos/memos) | Go、Connect/gRPC、多数据库、React；MIT | 数据访问、迁移与认证分别组织；事务包住读取校验与写入 | 不引入多用户、多数据库驱动和共享空间；归档并不等于软删除。 |
| [DailyTxT](https://github.com/PhiTux/DailyTxT) | 当前 v2 为 Go、SvelteKit、加密 JSON 文件；MIT | 月历阅读和按月聚合的个人日记行为 | 旧 Python 实现不是当前技术栈，文件锁不能替代 SQLite 的整批事务。 |
| [Trilium](https://github.com/TriliumNext/Trilium) | TypeScript、SQLite、Express/Electron；AGPL-3.0-or-later | 软删除与增量读取；实体和变更在同一事务中持久化 | 不引入整套知识树和同步引擎；techo 追加每次变动快照，不按实体覆盖历史。 |
| [MediaTracker](https://github.com/bonukai/MediaTracker) | TypeScript、Express、Knex、SQLite/PostgreSQL；MIT | 书影音类型清楚、业务层与存储层分开 | SPEC 只记看过的日期和一句话，不引入作品元数据抓取、评分、剧集或外部 ID。 |

另核实 [Journiv](https://github.com/journiv/journiv-app)，其 FastAPI/SQLModel/Alembic 分层与需求相近，但采用 PolyForm Noncommercial 加附加条款，Web 客户端专有，不作为宽松开源底座。

## 实现边界

techo 是一个模块化单体。HTTP 路由只解析输入和身份；services 负责业务事务；repositories 负责查询及持久化；SQLAlchemy 管理连接和事务，Alembic 管理 schema 版本。SQLite 是部署约束，不自行实现 ORM、数据库迁移框架或会话签名协议。

- 普通写和 batch 调用同一业务服务，但提交由外层事务决定。条目和 change snapshot 一起提交，整批失败一起回滚。
- SQLite 写事务先 `BEGIN IMMEDIATE`，再查询去重键和最大 sort。并发 batch 不会在先查后写之间插入重复条目。
- WAL 允许读写并存；busy timeout 等待短暂锁竞争；每次 HTTP 聚合读取用同一读快照。
- 变更时间在同一写事务内从数据库最后一个时间戳递增，至少相差一微秒。分页游标使用已提交快照的水位，避免把仍未提交的写入跳过去。
- 浏览器使用随机不透明 session，数据库只存 token 的 SHA-256；agent 使用独立环境 token。两者明确映射到 human/agent，作者字段不由客户端提供。
- 运行中的 WAL 数据库通过 SQLite backup API 备份。源码 Git、个人数据、凭据和备份各自管理。

## 具体源码依据

- shared-page 基准 [86e2a7ae](https://github.com/KKarsyline/shared-page/tree/86e2a7aeabd7de903aa1353a2b455c0b231d785b)：[许可](https://github.com/KKarsyline/shared-page/blob/86e2a7aeabd7de903aa1353a2b455c0b231d785b/LICENSE)、[核心与变更](https://github.com/KKarsyline/shared-page/blob/86e2a7aeabd7de903aa1353a2b455c0b231d785b/server/calendar_core.py)、[REST 鉴权与上传](https://github.com/KKarsyline/shared-page/blob/86e2a7aeabd7de903aa1353a2b455c0b231d785b/server/routes.py)、[seed](https://github.com/KKarsyline/shared-page/blob/86e2a7aeabd7de903aa1353a2b455c0b231d785b/server/seeder.py)。
- flatnotes：[入口、认证依赖和静态挂载](https://github.com/dullage/flatnotes/blob/7f5b773c9cb37cc84978079ed4790e7de38d3970/server/main.py)、[文件存储实现](https://github.com/dullage/flatnotes/blob/7f5b773c9cb37cc84978079ed4790e7de38d3970/server/notes/file_system/file_system.py)。
- Memos：[事务封装](https://github.com/usememos/memos/blob/88a20fefdb20962558aa8db04d5ba068aac201e8/store/transaction.go)、[SQLite schema](https://github.com/usememos/memos/blob/88a20fefdb20962558aa8db04d5ba068aac201e8/store/migration/sqlite/LATEST.sql)。
- DailyTxT：[当前版说明](https://github.com/PhiTux/DailyTxT/blob/4f9657c33f07b9383c72c841b6a4c0a684494f7f/README.md)、[按月文件读写](https://github.com/PhiTux/DailyTxT/blob/4f9657c33f07b9383c72c841b6a4c0a684494f7f/backend/utils/file_handling.go)。
- Trilium：[软删除和变更表](https://github.com/TriliumNext/Trilium/blob/5b9ccef51fbe08781312fe76add64d06228c6bcc/packages/trilium-core/src/assets/schema.sql)、[实体和变更原子保存](https://github.com/TriliumNext/Trilium/blob/5b9ccef51fbe08781312fe76add64d06228c6bcc/packages/trilium-core/src/becca/entities/abstract_becca_entity.ts)、[增量查询](https://github.com/TriliumNext/Trilium/blob/5b9ccef51fbe08781312fe76add64d06228c6bcc/packages/trilium-core/src/routes/api/sync.ts)。
- MediaTracker：[作品与个人记录模型](https://github.com/bonukai/MediaTracker/blob/22aedac26329893b6441d74d12be9a48e190ca9c/server/src/migrations/20210818142342_init.ts)。
- Journiv：[实际许可证](https://github.com/journiv/journiv-app/blob/c5ea6b171db2b9cc5f97c353766adea5801f43d2/LICENSE.md)。
- FastAPI：[多文件应用与 APIRouter](https://fastapi.tiangolo.com/tutorial/bigger-applications/)、[应用生命周期](https://fastapi.tiangolo.com/advanced/events/)。
- SQLAlchemy：[SQLite 事务控制与 BEGIN 事件](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html#enabling-non-legacy-sqlite-transactional-modes-with-the-sqlite3-or-aiosqlite-driver)。
