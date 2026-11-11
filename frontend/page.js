"use strict";
// techo · 一页的装修：贴纸、照片、小字、手写
// 依赖 app.js 里的 api / guard / toast / esc / $ 和 stickers.js 的 STICKERS。
// 坐标全是比例：物件中心 x、y 相对页宽页高；页固定 3:4。

const PAGE = (() => {
  const INK = ["#f4f2ee", "#2b2b2b", "#a9c2e6", "#e3bdb6", "#a9b8a0"];
  const BASE = { emoji: 11, photo: 38, text: 0 };
  const photoSrc = (id, size, hash) => `${API}/photos/${id}?size=${size}${hash ? `&h=${encodeURIComponent(hash)}` : ""}`;

  function releasePhotos(el) {
    el.querySelectorAll(".pi-photo img").forEach((img) => img._releasePhoto?.());
  }
  function loadPhoto(img, it, size) {
    const hash = it._hash || (typeof month !== "undefined" && month?.photos?.find((p) => String(p.id) === it.ref)?.hash);
    guard(async () => {
      try {
        // 装修只存 id；不知道内容 hash 时不能命中或写入裸 id 的长期缓存。
        const res = await fetch(photoSrc(it.ref, size, hash), { credentials: "same-origin", cache: hash ? "default" : "no-store" });
        if (!img.isConnected) return;
        if (res.status === 401) throw new AuthError();
        if (res.status === 404) { img.parentNode.dispatchEvent(new CustomEvent("gone", { bubbles: true })); return; }
        if (!res.ok) return;
        const blob = await res.blob();
        if (!img.isConnected) return;
        const src = URL.createObjectURL(blob);
        const release = () => { URL.revokeObjectURL(src); img.onload = img.onerror = null; img._releasePhoto = null; };
        img._releasePhoto = img.onload = img.onerror = release;
        img.src = src;
      } catch (err) {
        if (err instanceof AuthError) throw err;
        // 断网、服务暂不可用或图片解码失败都保留物件，不能保存成删除。
      }
    });
  }

  // ---------- 读写 ----------
  async function load(page) {
    const [deco, st] = await Promise.all([
      api(`/decorations?page=${encodeURIComponent(page)}`),
      api(`/strokes?page=${encodeURIComponent(page)}`),
    ]);
    return { page, version: deco.version, items: deco.items.map((x, i) => ({ ...x, _k: i })), strokes: st.strokes };
  }

  async function uploadPhoto(file, date) {
    const blob = await compress(file);
    const fd = new FormData();
    fd.append("file", blob, "photo.jpg");
    fd.append("date", date);
    const res = await fetch(`${API}/photos`, { method: "POST", credentials: "same-origin", body: fd });
    if (res.status === 401) throw new AuthError();
    if (res.status === 413) throw new Error("照片还是太大了，换一张试试。");
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data?.error?.message || `照片没传上去（${res.status}）`);
    return data;
  }

  // 手机原图动辄五六兆，nginx 只放 2MB 进来：先在手机上缩到长边 1600 再传。
  async function compress(file) {
    let src;
    try { src = await createImageBitmap(file, { imageOrientation: "from-image" }); }
    catch {
      src = await new Promise((ok, bad) => {
        const img = new Image();
        img.onload = () => ok(img); img.onerror = () => bad(new Error("这张图打不开，换一张试试。"));
        img.src = URL.createObjectURL(file);
      });
    }
    const w0 = src.width || src.naturalWidth, h0 = src.height || src.naturalHeight;
    for (const edge of [1600, 1200, 900]) {
      const k = Math.min(1, edge / Math.max(w0, h0));
      const c = document.createElement("canvas");
      c.width = Math.round(w0 * k); c.height = Math.round(h0 * k);
      const g = c.getContext("2d");
      g.fillStyle = "#fff"; g.fillRect(0, 0, c.width, c.height);
      g.drawImage(src, 0, 0, c.width, c.height);
      for (const q of [0.86, 0.78, 0.68]) {
        const blob = await new Promise((ok) => c.toBlob(ok, "image/jpeg", q));
        if (blob && blob.size < 1.8e6) return blob;
      }
    }
    throw new Error("照片压不下来，换一张试试。");
  }

  // ---------- 画 ----------
  function itemNode(it, thumb) {
    const n = document.createElement("div");
    n.className = `pi pi-${it.item_type}`;
    if (it.item_type === "sticker") {
      if (it.ref.startsWith("emoji:")) { n.classList.add("pi-emoji"); n.textContent = it.ref.slice(6); n.style.width = `${BASE.emoji}%`; }
      else {
        const name = it.ref.slice(5), s = STICKERS.src(name);
        if (!s) return null;
        n.innerHTML = `<img src="${s}" alt="" draggable="false">`;
        n.style.width = `${STICKERS.pack[name].w}%`;
      }
    } else if (it.item_type === "photo") {
      n.innerHTML = `<img alt="" draggable="false">${it.text ? `<span>${esc(it.text)}</span>` : ""}`;
      n.style.width = `${BASE.photo}%`;
      loadPhoto(n.querySelector("img"), it, thumb ? "thumb" : "full");
    } else {
      n.textContent = it.text;
      if (it.color) n.style.color = it.color;
    }
    place(n, it);
    return n;
  }
  function place(n, it) {
    n.style.left = `${it.x * 100}%`; n.style.top = `${it.y * 100}%`;
    n.style.zIndex = it.z;
    n.style.transform = `translate(-50%,-50%) rotate(${it.rotation}deg) scale(${it.scale})`;
  }
  function drawStrokes(canvas, strokes, extra) {
    const r = canvas.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
    if (!r.width) return;
    canvas.width = Math.round(r.width * dpr); canvas.height = Math.round(r.height * dpr);
    const g = canvas.getContext("2d");
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.lineCap = "round"; g.lineJoin = "round";
    for (const s of extra ? [...strokes, extra] : strokes) strokePath(g, s, r.width, r.height);
  }
  function strokePath(g, s, W, H) {
    const p = s.points;
    g.strokeStyle = s.color; g.fillStyle = s.color;
    if (p.length === 3) {
      g.beginPath(); g.arc(p[0] / 1e4 * W, p[1] / 1e4 * H, s.width * W * (0.6 + 0.8 * p[2] / 255) / 2, 0, 7); g.fill(); return;
    }
    for (let i = 3; i < p.length; i += 3) {
      g.lineWidth = s.width * W * (0.6 + 0.8 * (p[i - 1] + p[i + 2]) / 510);
      g.beginPath();
      g.moveTo(p[i - 3] / 1e4 * W, p[i - 2] / 1e4 * H);
      g.lineTo(p[i] / 1e4 * W, p[i + 1] / 1e4 * H);
      g.stroke();
    }
  }
  // 只读的小样，日历底卡里用
  function render(el, state, thumb = true) {
    releasePhotos(el);
    el.innerHTML = '<canvas class="ink"></canvas>';
    for (const it of [...state.items].sort((a, b) => a.z - b.z)) { const n = itemNode(it, thumb); if (n) el.appendChild(n); }
    requestAnimationFrame(() => drawStrokes(el.querySelector(".ink"), state.strokes));
  }

  // ---------- 编辑器 ----------
  let ed = null; // 当前打开的编辑状态

  async function open(page, date, onClose) {
    if (ed?.saving) return;
    const state = await load(page);
    if (ed?.saving) return;
    const root = document.createElement("div");
    root.className = "editor";
    root.innerHTML = `
      <div class="ed-top">
        <button data-a="cancel">close</button>
        <span class="it">${esc(page.startsWith("day:") ? page.slice(9).replace("-", ".") : page.slice(6).replace("-", "."))}</span>
        <span class="ed-sel" hidden><button data-a="front">↑</button><button data-a="del">delete</button></span>
        <button data-a="done" class="strong">done</button>
      </div>
      <div class="ed-stage"><div class="page editing"></div></div>
      <div class="ed-tray">
        <nav class="ed-tabs"><button data-t="pack" class="on">贴纸</button><button data-t="emoji">emoji</button><button data-t="photo">照片</button><button data-t="text">字</button><button data-t="pen">笔</button></nav>
        <div class="ed-pane"></div>
      </div>`;
    document.body.appendChild(root);
    const pageEl = $(".page", root);
    const editor = ed = { state, root, pageEl, page, date, sel: null, dirty: false, revision: 0, saving: false, mode: "move", ink: INK[0], inkW: 0.006, mine: [], pendingStrokes: new Set(), onClose };
    pageEl.innerHTML = '<canvas class="ink"></canvas>';
    for (const it of state.items) mount(it);
    tab("pack");
    requestAnimationFrame(fit);
    root.addEventListener("click", onClick);
    pageEl.addEventListener("gone", (e) => {
      if (ed !== editor) return;
      const it = state.items.find((x) => x._node === e.target.closest(".pi"));
      if (it) { remove(it); toast("有一张照片已经被删了，从这页拿掉了。"); }
    });
    bindGestures(pageEl);
    addEventListener("resize", fit);
  }

  function close(saved) {
    if (!ed || ed.saving) return;
    removeEventListener("resize", fit);
    const cb = ed.onClose;
    releasePhotos(ed.root);
    ed.root.remove(); ed = null;
    cb?.(saved);
  }
  function changed() { ed.dirty = true; ed.revision++; }

  function mount(it) {
    const n = itemNode(it, false);
    if (!n) return;
    it._node = n;
    ed.pageEl.appendChild(n);
  }
  function remove(it) {
    if (it._node) releasePhotos(it._node);
    it._node?.remove();
    ed.state.items = ed.state.items.filter((x) => x !== it);
    if (ed.sel === it) select(null);
    changed();
  }
  function topZ() { return ed.state.items.reduce((m, x) => Math.max(m, x.z), -1) + 1; }
  function add(it) {
    const full = { ref: null, text: null, color: null, x: 0.5, y: 0.45, scale: 1, rotation: Math.round(Math.random() * 10 - 5), z: topZ(), ...it, _k: Date.now() };
    ed.state.items.push(full);
    mount(full); select(full);
    changed();
    setMode("move");
  }
  function select(it) {
    ed.state.items.forEach((x) => x._node?.classList.toggle("sel", x === it));
    ed.sel = it;
    $(".ed-sel", ed.root).hidden = !it;
    const cap = $(".ed-pane .cap", ed.root);
    if (cap) { cap.hidden = it?.item_type !== "photo"; if (!cap.hidden) $("input", cap).value = it.text || ""; }
  }
  function redrawInk() { if (ed) drawStrokes($(".ink", ed.pageEl), ed.state.strokes, ed.live); }
  // 页固定 3:4，按舞台大小算出最大能放多大
  function fit() {
    if (!ed) return;
    const st = $(".ed-stage", ed.root).getBoundingClientRect();
    let h = st.height - 16, w = h * 0.75;
    if (w > st.width - 32) { w = st.width - 32; h = w / 0.75; }
    ed.pageEl.style.width = `${Math.floor(w)}px`; ed.pageEl.style.height = `${Math.floor(h)}px`;
    redrawInk();
  }

  function setMode(m) {
    ed.mode = m;
    ed.pageEl.classList.toggle("pen", m === "pen");
    if (m === "pen") select(null);
  }

  function tab(t) {
    ed.root.querySelectorAll(".ed-tabs button").forEach((b) => b.classList.toggle("on", b.dataset.t === t));
    const pane = $(".ed-pane", ed.root);
    setMode(t === "pen" ? "pen" : "move");
    if (t === "pack") pane.innerHTML = `<div class="tray-grid">${Object.keys(STICKERS.pack).map((k) => `<button data-s="pack:${k}"><img src="${STICKERS.src(k)}" alt="${k}"></button>`).join("")}</div>`;
    if (t === "emoji") pane.innerHTML = `<div class="tray-grid emoji">${STICKERS.EMOJI.map((e) => `<button data-s="emoji:${e}">${e}</button>`).join("")}</div>`;
    if (t === "photo") pane.innerHTML = `<label class="tray-row"><input type="file" accept="image/*" hidden><span>从相册选一张 →</span></label><p class="tray-tip">会做成一张拍立得。点选中后可以在下面写一行小字。</p>
      <div class="tray-row cap" hidden><input placeholder="照片底下写一句…" maxlength="200"><button data-a="cap">ok</button></div>`;
    if (t === "text") pane.innerHTML = `<form class="tray-row" data-f="text"><input placeholder="写一句…" maxlength="200"><button>add</button></form>${swatches()}`;
    if (t === "pen") pane.innerHTML = `${swatches()}<div class="tray-row"><span class="tray-tip">粗细</span>${[0.003, 0.006, 0.012].map((w) => `<button data-w="${w}" class="${w === ed.inkW ? "on" : ""}">${w < 0.005 ? "细" : w < 0.01 ? "中" : "粗"}</button>`).join("")}<button data-a="undo" style="margin-left:auto">撤销一笔</button></div>`;
    const editor = ed;
    const file = $("input[type=file]", pane);
    if (file) file.onchange = () => {
      if (ed !== editor || editor.saving) return;
      const f = file.files[0];
      if (!f) return;
      toast("在压缩、上传…");
      guard(async () => {
        const p = await uploadPhoto(f, editor.date);
        if (ed !== editor) return;
        add({ item_type: "photo", ref: String(p.id), _hash: p.hash, y: 0.4 });
        toast("贴上了");
      });
      file.value = "";
    };
    select(ed.sel);
    const form = $("form[data-f=text]", pane);
    if (form) form.onsubmit = (e) => {
      e.preventDefault();
      if (ed !== editor || editor.saving) return;
      const v = $("input", form).value.trim();
      if (!v) return;
      add({ item_type: "text", ref: "hand", text: v, color: ed.ink, y: 0.75 });
      $("input", form).value = "";
    };
  }
  function swatches() {
    return `<div class="tray-row">${INK.map((c) => `<button class="sw${c === ed.ink ? " on" : ""}" data-c="${c}" style="background:${c}" aria-label="${c}"></button>`).join("")}</div>`;
  }

  async function save(editor) {
    const revision = editor.revision;
    const items = editor.state.items.map(({ item_type, ref, text, color, x, y, scale, rotation }, i) => ({
      item_type, ref, text, color,
      x: +x.toFixed(4), y: +y.toFixed(4), scale: +scale.toFixed(3), rotation: +rotation.toFixed(1), z: i,
    }));
    // 按当前 z 排好再落号，保持前后关系
    const order = editor.state.items.map((x, i) => [x.z, i]).sort((a, b) => a[0] - b[0]).map((x) => x[1]);
    const sorted = order.map((i, z) => ({ ...items[i], z }));
    const res = await api(`/decorations?page=${encodeURIComponent(editor.page)}`, { method: "PUT", body: { version: editor.state.version, items: sorted } });
    editor.state.version = res.version;
    // 保存期间完成的上传、404 清理仍是新修改，不能随旧快照一起清掉。
    editor.dirty = editor.revision !== revision;
  }

  function onClick(e) {
    const b = e.target.closest("button, [data-s]");
    if (!b || !ed || ed.saving) return;
    const a = b.dataset;
    if (a.t) return tab(a.t);
    if (a.s) return add({ item_type: "sticker", ref: a.s, y: 0.3 + Math.random() * 0.3, x: 0.3 + Math.random() * 0.4 });
    if (a.c) { ed.ink = a.c; ed.root.querySelectorAll(".sw").forEach((x) => x.classList.toggle("on", x === b)); if (ed.sel?.item_type === "text") { ed.sel.color = a.c; ed.sel._node.style.color = a.c; changed(); } return; }
    if (a.w) { ed.inkW = +a.w; ed.root.querySelectorAll("[data-w]").forEach((x) => x.classList.toggle("on", x === b)); return; }
    if (a.a === "cancel") { if (!ed.dirty || confirm("摆的东西还没保存，就这样关掉？（手写的已经存了）")) close(false); return; }
    if (a.a === "done") {
      const editor = ed;
      if (editor.live) endInk({ pointerId: editor.liveId });
      editor.saving = true; editor.root.inert = true;
      return guard(async () => {
        try {
          if (editor.pendingStrokes.size) {
            const settled = await Promise.allSettled([...editor.pendingStrokes]);
            const failed = settled.find((result) => result.status === "rejected");
            if (failed) throw failed.reason;
          }
          if (editor.dirty) await save(editor);
          if (ed === editor && !editor.dirty) { editor.saving = false; close(true); }
        } finally { editor.saving = false; editor.root.inert = false; }
      });
    }
    if (a.a === "del" && ed.sel) return remove(ed.sel);
    if (a.a === "front" && ed.sel) { ed.sel.z = topZ(); place(ed.sel._node, ed.sel); changed(); return; }
    if (a.a === "cap" && ed.sel?.item_type === "photo") {
      const v = $(".cap input", ed.root).value.trim() || null;
      ed.sel.text = v; const old = ed.sel._node; const it = ed.sel;
      releasePhotos(old); old.remove(); mount(it); select(it); changed(); return;
    }
    if (a.a === "undo") {
      const editor = ed, id = editor.mine.pop();
      if (!id) return toast("这次没有可以撤销的笔画");
      trackStroke(editor, (async () => {
        await api(`/strokes/${id}`, { method: "DELETE", unversioned: true });
        editor.state.strokes = editor.state.strokes.filter((s) => s.id !== id);
        if (ed === editor) redrawInk();
      })());
    }
  }

  function trackStroke(editor, request) {
    // 跟踪原始 promise，不能把 guard 吞掉的失败当作保存成功。
    editor.pendingStrokes.add(request);
    guard(async () => {
      try { await request; }
      finally { editor.pendingStrokes.delete(request); }
    });
  }

  // ---------- 手势：一指拖，两指缩放旋转；笔模式下画 ----------
  function bindGestures(el) {
    const editor = ed;
    const editable = () => ed === editor && !editor.saving;
    const pts = new Map();
    let snap = null;
    const rect = () => el.getBoundingClientRect();
    const begin = () => {
      if (!ed.sel) { snap = null; return; }
      const v = [...pts.values()];
      snap = { it: { ...ed.sel }, v: v.map((p) => ({ ...p })) };
      if (v.length >= 2) {
        snap.d = Math.hypot(v[1].x - v[0].x, v[1].y - v[0].y);
        snap.a = Math.atan2(v[1].y - v[0].y, v[1].x - v[0].x);
        snap.c = { x: (v[0].x + v[1].x) / 2, y: (v[0].y + v[1].y) / 2 };
      }
    };
    el.addEventListener("pointerdown", (e) => {
      if (!editable()) return;
      el.setPointerCapture(e.pointerId);
      if (ed.mode === "pen") { startInk(e); return; }
      if (pts.size === 0) {
        const node = e.target.closest(".pi");
        const it = node && ed.state.items.find((x) => x._node === node);
        select(it || null);
        if (it?.item_type === "photo") tab("photo");
      }
      pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
      begin();
    });
    el.addEventListener("pointermove", (e) => {
      if (!editable()) return;
      if (ed.mode === "pen") { moveInk(e); return; }
      if (!pts.has(e.pointerId) || !snap) return;
      pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
      const r = rect(), v = [...pts.values()], it = ed.sel, s = snap.it;
      if (v.length === 1) {
        it.x = clamp(s.x + (v[0].x - snap.v[0].x) / r.width, -0.2, 1.2);
        it.y = clamp(s.y + (v[0].y - snap.v[0].y) / r.height, -0.2, 1.2);
      } else if (snap.d) {
        const d = Math.hypot(v[1].x - v[0].x, v[1].y - v[0].y);
        const a = Math.atan2(v[1].y - v[0].y, v[1].x - v[0].x);
        const c = { x: (v[0].x + v[1].x) / 2, y: (v[0].y + v[1].y) / 2 };
        it.scale = clamp(s.scale * d / snap.d, 0.15, 7);
        it.rotation = norm(s.rotation + (a - snap.a) * 180 / Math.PI);
        it.x = clamp(s.x + (c.x - snap.c.x) / r.width, -0.2, 1.2);
        it.y = clamp(s.y + (c.y - snap.c.y) / r.height, -0.2, 1.2);
      }
      place(it._node, it); changed();
    });
    const up = (e) => {
      if (!editable()) { pts.clear(); snap = null; return; }
      if (ed.mode === "pen") { endInk(e); return; }
      pts.delete(e.pointerId); begin();
    };
    el.addEventListener("pointerup", up);
    el.addEventListener("pointercancel", up);
    // 电脑上：滚轮缩放，按住 shift 滚轮旋转
    el.addEventListener("wheel", (e) => {
      if (!editable() || !ed.sel) return;
      e.preventDefault();
      const it = ed.sel;
      if (e.shiftKey) it.rotation = norm(it.rotation + e.deltaY * 0.2);
      else it.scale = clamp(it.scale * Math.exp(-e.deltaY * 0.002), 0.15, 7);
      place(it._node, it); changed();
    }, { passive: false });
  }
  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
  const norm = (d) => ((d + 540) % 360) - 180;

  function inkPoint(e, r) {
    const p = e.pointerType === "pen" && e.pressure > 0 ? Math.round(e.pressure * 255) : 128;
    return [Math.round((e.clientX - r.left) / r.width * 1e4), Math.round((e.clientY - r.top) / r.height * 1e4), p];
  }
  function startInk(e) {
    if (ed.live) return;
    ed.liveId = e.pointerId; ed.liveRect = ed.pageEl.getBoundingClientRect();
    ed.live = { color: ed.ink, width: ed.inkW, points: inkPoint(e, ed.liveRect) };
    redrawInk();
  }
  function moveInk(e) {
    if (!ed.live || e.pointerId !== ed.liveId) return;
    const evs = e.getCoalescedEvents ? e.getCoalescedEvents() : [e];
    for (const ev of evs) {
      if (ed.live.points.length >= 15000) break;
      const q = inkPoint(ev, ed.liveRect), p = ed.live.points, n = p.length;
      if (Math.abs(q[0] - p[n - 3]) + Math.abs(q[1] - p[n - 2]) < 12) continue;
      p.push(...q.map((v, i) => (i < 2 ? clamp(v, -2400, 12400) : v)));
    }
    redrawInk();
  }
  function endInk(e) {
    if (!ed.live || e.pointerId !== ed.liveId) return;
    const editor = ed, s = editor.live; editor.live = null;
    editor.state.strokes.push(s); redrawInk();
    trackStroke(editor, (async () => {
      try {
        const res = await api(`/strokes?page=${encodeURIComponent(editor.page)}`, { method: "POST", body: { strokes: [s] } });
        Object.assign(s, res.strokes[0]);
        if (ed === editor) editor.mine.push(s.id);
      } catch (err) {
        editor.state.strokes = editor.state.strokes.filter((x) => x !== s);
        if (ed === editor) redrawInk();
        throw err;
      }
    })());
  }

  return { open, load, render };
})();
