# techo 接口说明

## 0. 范围

面向单个用户及其 AI 助手的月历手账，包含日常记录、周/月目标、书影音、照片、贴纸和手写。用户通过浏览器记录，Agent 通过 API 协作。

## 1. 运行环境

Python 3.12、FastAPI、SQLite 和原生网页。路径、域名及服务用户由部署者配置；示例为 `/srv/techo`、`https://techo.example.com` 和 `techo`。静态页位于 `/techo/`，API 位于 `/techo/api/v1/`。

时间戳使用 `TECHO_TIMEZONE` 配置的 IANA 时区，默认 `Asia/Shanghai`；本文示例中的 `+08:00` 均以默认时区为准。

## 2. 鉴权

两种身份，只此两种：

| 身份 | 怎么进 | author 值 |
|---|---|---|
| User（浏览器） | `POST /api/v1/login` 交密码 → HttpOnly、Secure、SameSite=Lax 的会话 cookie，有效期 90 天 | `human` |
| AI 助手（程序） | 请求头 `X-Techo-Token: <token>` | `agent` |

- 密码和 token 从环境变量读：`TECHO_PASSWORD_HASH`（bcrypt/argon2 哈希）、`TECHO_AGENT_TOKEN`。放 `.env`，权限 600，不进 git。
- **author 由后端按身份决定**，不信任请求体里的 author。
- 登录接口加简单限速（同 IP 每分钟 5 次）。
- `GET /me` 返回当前身份 `{"author": "human"}` 或 `{"author": "agent"}`；`POST /logout` 返回 `{"ok": true}`，并在服务端撤销会话。
- 未登录访问 API 一律 401；前端静态页本身可以公开。
- Agent token 优先于 cookie；显式传入错误 token 时返回 401，不回退到 cookie。
- 浏览器写请求检查 Origin：缺省允许同源客户端，`Sec-Fetch-Site: cross-site` 拒绝，不符返回 403。限速按 nginx 覆写的真实客户端地址计数，不信任公网客户端自带的转发头。
- Cookie 名 `techo_session`，`Path=/techo/`，固定有效期 90 天；会话存入 SQLite，重启不失效。正式使用需要 HTTPS。

## 3. 数据模型

所有表都有：`id`（整数自增）、`author`（`human`|`agent`|`seed`）、`updated_by`、`created_at`、`updated_at`（ISO8601，带时区偏移）、`deleted_at`（软删除，可空）。

### 3.1 `notes` — 某一天的一句话
| 字段 | 类型 | 说明 |
|---|---|---|
| date | `YYYY-MM-DD` | 必填 |
| text | string | 必填，≤ 500 字 |
| mood | string，可空 | 一个 emoji 或短词，前端给选项，后端不校验内容 |

一天可以有多条（用户一条、AI 助手一条，或者更多）。

### 3.2 `media` — 看过/读过的东西
| 字段 | 类型 | 说明 |
|---|---|---|
| date | `YYYY-MM-DD` | 看完/读完那天 |
| kind | enum | `book` `film` `series` `show`（综艺） `other` |
| title | string | 必填 |
| note | string，可空 | 一句话 |

只记“看过”，不存评分。

### 3.3 `events` — 有日期的安排
| 字段 | 类型 | 说明 |
|---|---|---|
| date | `YYYY-MM-DD` | 必填 |
| time | `HH:MM`，可空 | 不填就是全天 |
| title | string | 必填 |
| kind | enum | `plan`（普通安排） `anniversary`（纪念日/生日） |
| place | string，可空 | |

### 3.4 `goals` — 周/月计划（目标和安排，不是密集待办）
| 字段 | 类型 | 说明 |
|---|---|---|
| scope | enum | `week` / `month` |
| period | string | 周用 ISO 周 `2026-W46`，月用 `2026-11` |
| text | string | 必填 |
| status | enum | `open` `done` `dropped`，默认 `open` |
| sort | int | 同一 period 内排序，默认追加到最后 |

## 4. 接口（前缀 `/techo/api/v1`，JSON，UTF-8）

### 4.1 读

- `GET /month?ym=2026-11` → 该月全部数据，前端一次拿完：
  ```json
  {
    "ym": "2026-11",
    "notes":  [ {...} ],
    "media":  [ {...} ],
    "events": [ {...} ],
    "goals":  { "month": [ {...} ], "weeks": { "2026-W45": [...], "2026-W46": [...] } }
  }
  ```
  `weeks` 包含与该月有交集的所有 ISO 周，即使该周无目标也返回空数组。已软删除的不返回。
- `GET /day?date=2026-11-08` → 返回 `date`、`ym`、`notes`、`media`、`events`、`goals`，只含那一天；`goals.weeks` 只有当天所在的 ISO 周。
- `GET /changes?since=<ISO8601>` → 自某时刻以来**另一方**新增/修改/删除的条目（User 调用返回 agent 的改动，AI 助手调用返回 human 的改动），按时间升序。
  ```json
  {"changes": [{"change_id": 1, "type": "note", "id": 1, "op": "created", "at": "...+08:00", "data": {"...": "完整条目"}}],
   "cursor": "...+08:00", "has_more": false}
  ```
  按实际操作者筛选另一方，而非条目原作者；seed 的初始创建不推送给任一方。每次变动保留独立快照，删除也可见。`since` 必须含时区；以严格晚于 since 查询。可选 `limit` 默认 500、最大 1000；总是保存返回的 cursor，有 `has_more` 时继续翻页。cursor 取同一读快照中的已提交变更，不采用请求结束时的墙钟，避免并发漏记。
- 后端完整接收 `/techo/` 前缀，nginx 不剥掉前缀；默认监听 `127.0.0.1:8875`。

### 4.2 写（四类资源同一套）

`POST /notes` `PATCH /notes/{id}` `DELETE /notes/{id}`；`/media`、`/events`、`/goals` 同理。

- `POST` 返回 `201` 和完整条目；`PATCH` 返回 `200` 和完整条目；`DELETE` 返回 `200 {"ok": true}`。
- 传入 `author`、`updated_by`、`id`、时间戳或未知字段返回 400。必填文本去首尾空白后不能为空；PATCH 支持将可空字段显式清空，不能清空必填字段。
- `PATCH` 只改传入的字段；PATCH、DELETE 必须携带当前版本的强 `If-Match`，见第 8 节。
- **谁都能改谁的**，但每次修改记 `updated_by`。
- `DELETE` 是软删除。
- `POST /goals/reorder`：`{"period": "2026-W46", "ids": [3,1,2], "versions": {"3":"...+08:00","1":"...+08:00","2":"...+08:00"}}`。`ids` 必须恰好包含该 period 全部未删除目标且不重复；列表过期、跨 period 或任一版本过期返回 409，防止排序时遗漏并发新增或删除的目标。无目标时 `ids=[]`、`versions={}`。ISO 周校验真实周数，例如不存在的 W53 返回 400。

### 4.3 批量写（给 AI 助手补记用）

`POST /batch`：
```json
{ "items": [
  { "type": "note",  "date": "2026-11-08", "text": "完成一页读书笔记并整理下周学习计划", "mood": "😋" },
  { "type": "media", "date": "2026-11-07", "kind": "show", "title": "现在就出发" }
] }
```
- 只接受 agent token。接受 1–1000 条；整批一个事务，任何一条不合法就整批回滚，返回出错下标和原因。
- `type` 可为 `note`、`media`、`event`、`goal`。返回 `{"created":[{"index":0,"type":"note","item":{...}}],"skipped":[{"index":1,"type":"note","id":1}]}`；index 从 0 开始。校验失败错误对象附 `index`。
- **去重**：同一天、同一 type、同一 title/text（去首尾空白后完全相同）曾存在时跳过，不报错，返回里列出 `skipped`。goal 没有 date，去重键为 scope+period+text。历史映射和可选稳定 `source_key` 的规则见第 8 节，人工改写、删除后重跑也不会重建旧内容。

### 4.4 其他

- `GET /healthz` → `{"ok": true}`，不需要鉴权。
- 已鉴权时 `GET /openapi.json` 提供接口清单和请求结构；响应模型以本文为准。
- 静态前端目录可以缺失：此时静态入口返回 404，API 正常工作；随后加入前端文件即可读取，不靠后端自动创建或改写 `frontend/`。

## 5. 照片、贴纸与手写

### 5.0 约束

- nginx 对 `/techo/` 的请求体上限 `client_max_body_size 2m`（2 MiB），不改。**照片由前端先压缩再传**，后端单次上传上限 2 MiB。
- systemd 部署只允许写项目 `data/`，照片只写 `data/photos/`（由 `Settings.photos_path` 从数据目录派生）。
- 单 worker Uvicorn + SQLite，沿用 `Database.transaction()`、`APIError`、鉴权依赖、Origin 检查和错误格式。
- 页面坐标全部是比例。一张“页”固定宽高比 3:4（宽:高），是前端约定，后端不关心。
- 页名 `page`：`day:YYYY-MM-DD`（必须是真实日期）或 `month:YYYY-MM`；不合法返回 400，`field: "page"`。

### 5.1 照片 photos

条目形状（month/day、POST、PATCH、`/changes` 的 data 都是这个）：
```json
{"id": 12, "date": "2026-11-08", "caption": "示例照片", "width": 1600, "height": 1200,
 "hash": "a3f9c2e1b07d", "author": "human", "updated_by": "human",
 "created_at": "...+08:00", "updated_at": "...+08:00", "deleted_at": null}
```
`width`/`height` 是成品 full.webp 的像素尺寸（已按 EXIF 转正）。`hash` 是成品 full.webp 内容 SHA-256 的前 12 位，前端拼 `photos/{id}?size=thumb&h={hash}` 做缓存键（`h` 后端忽略）。`deleted_at` 与四类资源一致，正常读取恒为 null，删除快照里有值。文件路径不对外暴露。

- `POST /photos`：`multipart/form-data`，字段 `file`（必填，恰好一个文件）、`date`（必填）、`caption`（可选，去空白后 ≤200，空串当 null）。其他字段、重复字段返回 400。
  - 整个请求体 > 2 MiB → 413 `payload_too_large`（先看 Content-Length，无 Content-Length 时边读边计数）。
  - 按**内容**识别，只收 JPEG / PNG / WebP，文件名和 part 的 Content-Type 不参与判断；其他格式、空文件或解码失败 → 400 `validation_error`，`field: "file"`。像素总数上限 5000 万，在解码前检查。
  - 处理：按 EXIF 方向转正；带 ICC 的 RGB 图先转换到 sRGB；有透明通道的图铺白底；转 RGB；丢掉全部元数据（EXIF、GPS、XMP、ICC 都不留）。full = 长边 ≤1600 的 WebP（质量 80，超过 400KB 每次降 5，最低 60）；thumb = 长边 ≤400 的 WebP（质量 70）。只缩不放。不存原图。
  - 文件放 `data/photos/YYYY/MM/`（按上传时的 date），文件名 `{id}-{内容哈希12位}-{nonce}-{full|thumb}.webp`，其中 nonce 是每次上传的 32 位十六进制随机串，避免回滚后复用 id 时清理误删其他上传的文件；先写同目录临时文件再 rename；目录 700、文件 600。行和文件在同一个写事务里落地，事务提交失败会删掉本次写的文件。
  - 返回 201 + 条目 + `ETag: "<updated_at>"`。
- `GET /photos/{id}?size=full|thumb`（默认 full）：要鉴权（cookie 或 agent token）；不存在或已软删 → 404；size 其他值 → 400 `field: "size"`。成功时 `Content-Type: image/webp`、`Cache-Control: private, max-age=31536000, immutable`。`privacy_headers` 中间件只对**成功的照片读取**豁免 `no-store`，401/404/400 等错误响应仍为 `no-store`。
- `PATCH /photos/{id}`：JSON，可改 `caption`（可显式设为 null 或空串清空）、`date`（不能为 null；改 date 不搬文件）。图片本身不能改，`hash`/`width` 等字段返回 400。`DELETE /photos/{id}`：软删除，文件保留。两者必须带 `If-Match`，规则同第 8 节（缺失/弱/格式错 400，过期 409）。PATCH 返回 200 + 条目 + ETag；DELETE 返回 `{"ok": true}`。
- `/month` 和 `/day` 的返回加 `"photos": [...]`，按 date、id 升序，不含软删。
- `/changes`：照片的 created / updated / deleted 进变更流，`type: "photo"`，按实际操作者筛另一方。
- `/batch` 不支持照片（`type: "photo"` 返回 400）。

### 5.2 贴纸装修 decorations

一页的装修整页读、整页写。
```json
{"page": "day:2026-11-08", "version": "2026-11-10T12:00:00.000001+08:00",
 "items": [
   {"item_type": "sticker", "ref": "pack:tape-sage", "text": null, "color": null, "x": 0.5, "y": 0.12, "scale": 1.0, "rotation": -4.0, "z": 0},
   {"item_type": "photo",   "ref": "12", "text": null, "color": null, "x": 0.4, "y": 0.4, "scale": 1.0, "rotation": 3.0, "z": 1},
   {"item_type": "text",    "ref": "hand", "text": "一个安静的下午", "color": "#f4f2ee", "x": 0.6, "y": 0.8, "scale": 1.0, "rotation": 0.0, "z": 2}
 ]}
```
- `GET /decorations?page=…`：没装修过的页返回 `{"page": …, "version": null, "items": []}`。
- `PUT /decorations?page=…`：body `{"version": <上次读到的 version，或 null>, "items": [...]}`，整页覆盖。`version` 必须显式给出（从未装修过的页传 null）；与库里当前值不一致 → 409 `conflict`（`field: "version"`），不改数据。version 按时间点比较，换时区写法也算同一个。成功返回 200 和新的 `{page, version, items}`（items 按 z、再按提交顺序）。写空数组合法（清空这一页），清空后 version 仍是一个新时间戳，不会回到 null。新 version 严格大于旧 version。
- 每个物件的字段：`item_type`、`x`、`y` 必填；`ref`、`text`、`color` 默认 null，`scale` 默认 1，`rotation` 默认 0，`z` 默认 0。返回里总是给齐 9 个字段，数值字段为浮点（`z` 为整数）。
- 校验（不合法一律 400 `validation_error`；条目错误 `field` 形如 `items.3.ref`，并带 `index: 3`）：
  - `items` 0–200 条；body 和物件的未知字段都拒绝。
  - `item_type` ∈ `sticker` / `photo` / `text`。
  - sticker：`ref` 必填，1–100 字符，必须以 `emoji:` 或 `pack:` 开头；`text` 必须为 null。
  - photo：`ref` 是十进制照片 id 字符串（不带前导 0），对应照片必须存在且未软删；`text` 可选（拍立得底下的小字，去空白后 ≤200，空串当 null）。
  - text：`text` 必填，去空白后 1–200（保存去空白后的值）；`ref` 可空或 1–40 字符的样式名。
  - `color`：null 或 `#rrggbb`（大小写均可，原样保存）。
  - `x`、`y`：物件**中心点**相对页宽、页高，范围 [-0.25, 1.25]。`scale` [0.1, 8]。`rotation` 角度 [-360, 360]。`z` 整数 [0, 10000]。数值必须是 JSON 数字（字符串、布尔不收），x/y/scale/rotation 必须是有限数。
- 照片被软删后，已有装修里引用它的 photo 物件仍会在 GET 中原样返回；但再次 PUT 时这个物件会被拒（400），前端需要先去掉它。
- 存储：`decorations` 表（一行一个物件，带提交顺序 `position`）+ `pages` 表（`page` 主键、`version`、`updated_by`）。
- 装修不进 `/changes`，不进 `/batch`。

### 5.3 笔迹 strokes

一笔一行，只增只删，不能改。
```json
{"id": 31, "page": "day:2026-11-08", "color": "#f4f2ee", "width": 0.006,
 "points": [1200, 3400, 128, 1215, 3410, 140], "author": "human", "created_at": "...+08:00"}
```
- `points`：扁平整数数组，每三个数一个采样点 `[x, y, p]`。x、y 是页宽、页高的万分比（0–10000，允许越界到 [-2500, 12500]）；p 是压感 0–255（没有压感的设备写 128）。长度必须是 3 的倍数，一笔 1–5000 个点（3–15000 个数）。必须是 JSON 整数，浮点、布尔、字符串都拒绝。
- `width`：笔宽相对页宽，[0.0005, 0.05]。`color`：`#rrggbb`。两者必填。
- `GET /strokes?page=…` → `{"page": …, "strokes": [...]}`，未删除的，id 升序。
- `POST /strokes?page=…`：body `{"strokes": [{"color", "width", "points"}, ...]}`，一次 1–50 笔，整批一个事务（任一笔不合法整批 400，`field` 形如 `strokes.1.points`，带 `index`）；返回 201 `{"strokes": [完整条目...]}`，顺序同请求。一页未删除的笔画上限 3000，本批加入后超过就 409 `conflict`，整批不写。
- `DELETE /strokes/{id}`：软删除，不需要 `If-Match`，重复删除也返回 200 `{"ok": true}`；不存在的 id → 404。任何一方都能删任何一笔。
- 笔迹不进 `/changes`，不进 `/batch`。

### 5.4 /month 的标记

`/month` 返回再加 `"decorated_pages": ["day:2026-11-08", "month:2026-11"]`：该月范围内（每一天的 `day:` 页加上 `month:` 页本身），至少有一个装修物件或一笔未删笔迹的页名，按字符串升序（所以 `day:` 页在前、`month:` 页在最后）。清空过的页、笔迹全删的页不在列表里。`/day` 不加这个字段。

`/month` 同时返回 `"page_peeks"`：以页名为键，值为该页最多 6 个最上层的贴纸/照片物件，每项只含 `item_type`、`ref`、`x`、`y`、`scale`、`rotation`、`z`，用于月历格子的缩略图；文字和笔迹不进入 `page_peeks`。没有可展示物件的页不出现在这个对象里。

### 5.5 迁移与依赖

- Alembic `0003` 只新建 `photos`、`pages`、`decorations`、`strokes` 四张表，不动旧数据；启动时自动跑。
- 依赖：`Pillow`、`python-multipart` 已写进 `server/requirements.in` 并锁定在 `requirements.txt`。
- CLI（`tools/techo_client.py`）：`photo-add --date D --file PATH [--caption C]`（本地先检查整个请求 ≤2 MiB）、`decorations PAGE`、`strokes PAGE`（后两个只读）。
- `tools/backup.py` 会把 `data/photos/` 整个目录复制进备份并写入校验清单。

## 6. 每年都有的日子（seed）

启动时读 `seed.json`，把纪念日铺到未来两年，`author=seed`、`kind=anniversary`，重复启动不写重（按 date+title 判重）。格式：
```json
[
  {"month_day": "01-01", "title": "年度回顾（示例）"},
  {"month_day": "06-01", "title": "阅读计划回顾（示例）"},
  {"day_of_month": 1, "title": "月度目标回顾（示例）"}
]
```
支持 `month_day`（每年）和 `day_of_month`（每月）。从配置时区的当天起、到两年后同日之前生成；不存在的日期跳过（如非闰年 02-29、没有 31 日的月份）。空 `seed.json` 表示暂未录入。seed 使用独立稳定键，手动修改或软删除后重启不会重建同一条，不覆盖人工编辑。农历生日不自动算，AI 助手每年手动加。

## 7. 错误格式

```json
{ "error": { "code": "validation_error", "message": "date 格式应为 YYYY-MM-DD", "field": "date" } }
```
状态码：400 校验、401 未登录、403 身份或来源无权限、404 不存在、409 冲突、429 限速、500。

## 8. 编辑冲突与幂等

- batch 各类 item 可附可选 `source_key`（去首尾空白后 1–200 字符），例如 `chat:message-123:note`。同一自动补记始终复用同一个 key，不使用批次时间或列表下标生成。key 在四类资源间全局唯一；已绑定到其他 type 时整批返回 409，`error.index` 指出位置。
- `source_key` 标识写入来源，命中后只返回 skipped 和原 id，不用重跑的正文覆盖人工修改；原条目软删除后也保持 skipped。需要修改既有条目时使用带版本条件的 PATCH；明确要创建新来源条目时使用新 key。
- 未带 key 的旧 batch 继续支持，按原有 date/type/text/title（goal 为 scope/period/text）生成稳定内容标识并保存历史映射。原记录编辑或删除后重跑旧内容仍 skipped，不会恢复旧正文或复活删除记录。新版本迁移从既有 change snapshots 回填历史标识；普通创建和编辑也保留内容标识。仅保存哈希与资源引用，不将这些标识作为用户可修改字段。
- 去重映射与资源、变更日志在同一事务提交或回滚。显式新 `source_key` 仍先对当前未删除内容去重；手动普通 POST 仍允许有意创建相同内容。已删除内容不再通过无 key 的自动重跑重建。
- 四类资源 PATCH、DELETE **必须**带 `If-Match: "<该条目的 updated_at>"`。使用用户当前看到的版本，不在提交时偷偷读取新版本再覆盖。POST 与 PATCH 成功响应同时提供相同格式的 ETag；month/day 中的 `updated_at` 可直接用于组成 If-Match。缺少、弱 ETag、通配符或格式错误返回 400，版本过期返回 409。检查与写入在同一事务内完成，冲突不改变数据或 change log。
- `/goals/reorder` 必须带 `versions`，版本必须与当前整组目标一一对应；集合或任一版本过期均返回 409。
- CLI reorder 必须带 `--versions-file <json文件>`，文件是 id 到 `updated_at` 的对象；不自动刷新版本。CLI 的 `TECHO_BASE_URL` 只允许 HTTPS，或 host 严格为 `127.0.0.1`、`localhost`、`::1` 的本机 HTTP；拒绝其他明文 HTTP 地址和重定向。