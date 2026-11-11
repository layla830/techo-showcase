# 前端接入与双人编辑验收

接口以 SPEC 第 4 节为准；照片、装修、笔迹以 SPEC 第 5 节为准。前端已接入现有编辑、删除及目标状态切换的版本条件。以下是对接合同和手机验收项目。

## 编辑与删除

month/day 的每条记录都有 `updated_at`。打开编辑器时保存这个值，提交时加双引号作为强 ETag；不要在提交前获取新版本替换它。POST、PATCH 成功响应也有 ETag，并返回完整新记录。

```js
const openedVersion = note.updated_at;
const response = await fetch(`/techo/api/v1/notes/${note.id}`, {
  method: "PATCH",
  credentials: "same-origin",
  headers: {
    "Content-Type": "application/json",
    "If-Match": JSON.stringify(openedVersion)
  },
  body: JSON.stringify({ text: editedText })
});
```

DELETE 采用同一个 `If-Match` 请求头，没有 JSON 请求体。四类资源都执行版本检查。

- 200：使用响应中的新记录更新本地状态，不继续沿用旧版本。
- 400：缺少或不合法的 If-Match、请求字段错误；按 error.field 展示。
- 409：保留用户尚未保存的文字，重新读取相关月/日和 changes，提示另一方已经修改或重新排序。让用户比较后决定如何提交，不自动把新版本填入并重试旧内容。
- 404：条目不存在或已软删除，保留未保存输入供用户处理，不自动通过 POST 重建。

服务器在同一 SQLite 写事务里完成比较和写入，冲突不产生条目修改、内容去重映射或 change snapshot。

## 目标排序

从已显示的完整目标列表保存版本映射。拖动只改变 ids 的顺序；versions 来自拖动前的视图，不能在提交时刷新。

```js
const versions = Object.fromEntries(goals.map(goal => [String(goal.id), goal.updated_at]));
const body = { period, ids: reorderedIds, versions };
```

POST `/techo/api/v1/goals/reorder`。ids 和 versions 必须覆盖该 period 全部未删除目标。即便 id 集合没变，只要另一方改过任一目标或重新排过序，也返回 409。空周期使用 ids=[]、versions={}。

CLI 同样从先前视图保存版本文件：

```sh
.venv/bin/python tools/techo_client.py reorder --period 2026-W46 --ids 3 1 2 --versions-file /private/path/versions.json
```

文件是 JSON 对象，键为 id，值为实际读取的 updated_at。CLI 不会替使用者刷新版本。

## 自动补记

建议为每个逻辑条目在首次准备时保存稳定 `source_key`，后续重试复用。例如：

```json
{
  "items": [
    {"type":"note","source_key":"chat:message-123:note","date":"2026-11-09","text":"示例补记"},
    {"type":"media","source_key":"chat:message-124:media","date":"2026-11-09","kind":"book","title":"示例书名"}
  ]
}
```

每个 key 在四类资源间全局唯一。来源可使用不可变消息 id 加类型和稳定子标识；不要每晚生成新 key，不要使用会变的批次时间、正文或列表位置。同 key 已命中后返回 skipped 和原 id，不会覆盖手动修改，也不会恢复软删除记录。同 key 被误用于其他类型时整批 409，并给出错误 index。

不带 key 的旧批次仍支持：后端记录内容的历史哈希，人工编辑、删除后重跑旧批次仍跳过。0002 迁移从旧 change snapshots 和现有条目回填这些标识。这个兼容逻辑无法识别从未见过、正文又变化的新来源，所以新补记应提供 source_key。

确实要修改已入库的补记时，读取其当前版本并 PATCH。确实要新建另一来源条目时使用全新 key；当前活跃内容相同仍会去重。普通手动 POST 不受自动补记的历史去重限制。

## 静态入口与本机调试

纯后端 checkout 可没有 frontend/。GET `/techo/` 此时返回 404，API 正常；加入 index.html、CSS、JS 后，同一应用即可读取。后端不生成或改写前端目录。

浏览器会话仍要求 HTTPS。CLI 允许公网 HTTPS，以及严格为 127.0.0.1、localhost、::1 的本机 HTTP；不接受其他明文 HTTP，不跟随重定向。

## 照片

照片必须在前端压缩后再传：nginx 对整个请求体限 2 MiB，超过时 **nginx 直接返回 HTML 的 413，不是 JSON**；后端自己也限 2 MiB，返回 JSON 的 413 `payload_too_large`。所以前端判断 413 时只看状态码，不要假设一定能解析出 `error`。建议压到长边 1600～2048、JPEG/WebP 质量 0.8 左右再传，后端会再统一转成 WebP。

上传用 `FormData`，**不要手动设 Content-Type**（浏览器会自动带 boundary）：

```js
const form = new FormData();
form.append("file", blob, "photo.jpg");   // Blob/File，JPEG、PNG 或 WebP；HEIC 不收
form.append("date", "2026-11-08");
form.append("caption", "sushi date");     // 可选；空串当 null
const response = await fetch("/techo/api/v1/photos", {
  method: "POST", credentials: "same-origin", body: form
});
// 201
// {"id":12,"date":"2026-11-08","caption":"sushi date","width":1600,"height":1200,
//  "hash":"a3f9c2e1b07d","author":"human","updated_by":"human",
//  "created_at":"2026-11-10T20:01:02.123456+08:00","updated_at":"2026-11-10T20:01:02.123456+08:00",
//  "deleted_at":null}
```

- 400 `field: "file"`：不是 JPEG/PNG/WebP、文件损坏、空文件或超过 5000 万像素；`field: "date"` / `"caption"`：表单字段问题。多传的字段也是 400。
- `width`/`height` 是转正后成品的尺寸，可以直接用来算宽高比。

显示图片直接用 `<img>`，同源 cookie 会自动带上；用 `hash` 做缓存键，图片内容永远不变：

```html
<img src="/techo/api/v1/photos/12?size=thumb&h=a3f9c2e1b07d" loading="lazy">
<img src="/techo/api/v1/photos/12?size=full&h=a3f9c2e1b07d">
```

成功响应带 `Cache-Control: private, max-age=31536000, immutable`。照片删除后再取是 404（`<img>` 的 onerror）。

改说明或日期、删除都要带 `If-Match`，和四类资源一样：

```js
await fetch(`/techo/api/v1/photos/${photo.id}`, {
  method: "PATCH", credentials: "same-origin",
  headers: {"Content-Type": "application/json", "If-Match": JSON.stringify(photo.updated_at)},
  body: JSON.stringify({caption: "新的说明", date: "2026-11-09"})   // caption 可传 null 清空；date 不能为 null
});
// 200 + 新条目 + ETag；过期 409；缺 If-Match 400
await fetch(`/techo/api/v1/photos/${photo.id}`, {
  method: "DELETE", credentials: "same-origin",
  headers: {"If-Match": JSON.stringify(photo.updated_at)}
});
// 200 {"ok":true}
```

`/month`、`/day` 新增 `photos` 数组（按 date、id 升序）；`/changes` 里会出现 `type: "photo"` 的 created/updated/deleted。

## 贴纸装修

```js
const page = "day:2026-11-08";          // 或 "month:2026-11"
const state = await (await fetch(`/techo/api/v1/decorations?page=${encodeURIComponent(page)}`,
  {credentials: "same-origin"})).json();
// 没装修过：{"page":"day:2026-11-08","version":null,"items":[]}
```

拖完一次性整页保存，`version` 用**打开这一页时读到的值**（没装修过就是 null），这个字段必须带：

```js
const response = await fetch(`/techo/api/v1/decorations?page=${encodeURIComponent(page)}`, {
  method: "PUT", credentials: "same-origin",
  headers: {"Content-Type": "application/json"},
  body: JSON.stringify({
    version: state.version,
    items: [
      {item_type: "sticker", ref: "pack:tape-sage", x: 0.5, y: 0.12, rotation: -4, z: 0},
      {item_type: "photo", ref: "12", text: "拍立得小字", x: 0.4, y: 0.4, rotation: 3, z: 1},
      {item_type: "text", ref: "hand", text: "sushi date", color: "#f4f2ee", x: 0.6, y: 0.8, z: 2}
    ]
  })
});
// 200 {"page":"day:2026-11-08","version":"2026-11-10T20:05:00.000001+08:00","items":[...9 个字段齐全，按 z 排...]}
```

- 保存成功后**用返回的新 `version` 替换本地的**，下一次保存要用它。
- 409：另一方（或另一个标签页）先保存过。重新 GET，让用户决定，不要自动拿新 version 覆盖。
- 400：`error.field` 形如 `items.3.ref`，`error.index` 是第几个物件。常见原因：sticker 的 ref 不以 `emoji:`/`pack:` 开头、sticker 带了 text、x/y 越出 [-0.25, 1.25]、scale 不在 [0.1, 8]、z 不是 0–10000 的整数、photo 物件引用的照片已删除。
- photo 物件的 `ref` 是**字符串**形式的照片 id（`"12"`，不是数字 12）。照片被删后，GET 仍会返回引用它的物件，前端显示时跳过；保存前要把它从 items 里去掉，否则整页 400。
- x/y 是物件中心点相对页宽、页高的比例（页面 3:4）。`ref`、`text`、`color`、`scale`、`rotation`、`z` 可省略（默认 null/null/null/1/0/0）。清空整页：`items: []`。

`/month` 新增 `decorated_pages`：该月有装修物件或未删笔迹的页名列表（`day:` 页在前，`month:` 页在最后），用来在月历上打标记。

## 笔迹

```js
const page = "day:2026-11-08";
await fetch(`/techo/api/v1/strokes?page=${encodeURIComponent(page)}`, {credentials: "same-origin"});
// {"page":"day:2026-11-08","strokes":[{"id":31,"page":"day:2026-11-08","color":"#f4f2ee","width":0.006,
//   "points":[1200,3400,128,1215,3410,140],"author":"human","created_at":"...+08:00"}]}

const response = await fetch(`/techo/api/v1/strokes?page=${encodeURIComponent(page)}`, {
  method: "POST", credentials: "same-origin",
  headers: {"Content-Type": "application/json"},
  body: JSON.stringify({strokes: [
    {color: "#f4f2ee", width: 0.006, points: [1200, 3400, 128, 1215, 3410, 140]}
  ]})
});
// 201 {"strokes":[完整条目，顺序同请求]}

await fetch(`/techo/api/v1/strokes/31`, {method: "DELETE", credentials: "same-origin"});
// 200 {"ok":true}，重复删也是 200；不存在 404。不需要 If-Match。
```

- `points` 必须是**整数**：x、y 用 `Math.round(ratio * 10000)`，压感 `Math.round(pressure * 255)`，没有压感写 128。浮点会被 400。
- 一笔 1–5000 个点，一次最多 50 笔；一页最多 3000 笔，超了 409（撤销/删除后再画）。
- 撤销 = DELETE 那一笔的 id，所以 POST 之后要记下返回的 id。
- 笔迹和装修都不进 `/changes`，对方的新笔迹要重新 GET 才看得到。

## 前端完成后的手机验收

这些项目要在真实前端上执行，后端 API 测试不能替代：

1. 手机登录，新建、编辑、删除每日记录；重新加载后显示和署名正确。
2. 书影音、日程和周月目标分别执行相同的写入、刷新流程，验证月末与跨月周。
3. 手机打开旧版本后让AI 助手修改同一字段，再保存手机内容：显示 409，保留未保存文字，不覆盖AI 助手的修改。
4. 反向执行：AI 助手持有旧版本时由手机编辑，程序 PATCH 同样得到 409；旧版本 DELETE 也被拒绝。
5. 两方对同一组目标先后拖动排序，旧版本提交得到 409；添加、删除目标后旧排序也被拒绝。
6. 自动补记后用手机改写正文，再重跑原 batch；仅保留手机版本。再删除该条目并重跑，记录保持删除。
7. 重启后确认数据、会话、source_key 映射和增量游标仍然有效。
8. 手机拍一张竖拍照片（带定位）上传：显示方向正确；下载成品确认不含定位信息；超过 2MB 的原图前端会先压缩。
9. 同一页两边各开一份装修，先后保存：后保存的一方得到 409，重新读取后再保存。
10. 在一页上写几笔、撤销一笔，刷新后笔迹一致；月历上该天出现装修/笔迹标记。

部署完成后，首次手机登录仍需按上述项目验收；页面可访问不等于完整手机操作验收。后续维护遵循 [OPERATIONS.md](OPERATIONS.md) 的备份流程。
