"use strict";
// techo 前端 · AI 助手
// 页面挂在 /techo/，接口走相对路径 api/v1/…；浏览器靠 cookie 登录。

const API = "api/v1";
const MONTHS = ["January","February","March","April","May","June","July","August","September","October","November","December"];
const WK = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"];
const KIND = { book: "书", film: "电影", series: "剧", show: "综艺", other: "其他" };
const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pad = (n) => String(n).padStart(2, "0");
const ymd = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const ymOf = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}`;
const who = (a) => (a === "agent" ? "AI" : "USER");

function isoWeek(d) {
  const t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  const day = t.getUTCDay() || 7;
  t.setUTCDate(t.getUTCDate() + 4 - day);
  const y = t.getUTCFullYear();
  const w = Math.ceil(((t - Date.UTC(y, 0, 1)) / 864e5 + 1) / 7);
  return `${y}-W${pad(w)}`;
}

// ---------- 网络 ----------
class AuthError extends Error {}
async function api(path, opts = {}) {
  const headers = opts.body ? { "content-type": "application/json" } : {};
  if ((opts.method === "PATCH" || opts.method === "DELETE") && !opts.unversioned) {
    if (typeof opts.version !== "string" || !opts.version) throw new Error("记录版本缺失，请重新读取。");
    headers["If-Match"] = JSON.stringify(opts.version);
  }
  const res = await fetch(`${API}${path}`, {
    method: opts.method || "GET",
    credentials: "same-origin",
    headers,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (res.status === 401) throw new AuthError();
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const error = new Error(data?.error?.message || `出错了（${res.status}）`);
    error.status = res.status;
    throw error;
  }
  return data;
}
let toastTimer;
function toast(msg) {
  let el = $(".toast");
  if (!el) { el = document.createElement("div"); el.className = "toast"; document.body.appendChild(el); }
  el.textContent = msg; el.classList.add("on");
  clearTimeout(toastTimer); toastTimer = setTimeout(() => el.classList.remove("on"), 2200);
}
async function guard(fn) {
  try { return await fn(); }
  catch (e) {
    if (e instanceof AuthError) showLogin();
    else if (e.status === 409) toast("记录已被另一方修改或重新排序；请先复制未保存文字，再重新读取比较。");
    else toast(e.message);
  }
}

// ---------- 状态 ----------
const today = new Date();
let cursor = new Date(today.getFullYear(), today.getMonth(), 1);
let month = null;      // /month 的返回
let tab = "month";
let openDate = null;   // 当前打开的那一天
let sheetDate = null;
const displayedRecords = new WeakMap();
const noteDrafts = new Map();
// 版本跟随已渲染的行，不能从后台刷新后的 month 偷换。
function rememberRows(root, selector, records) {
  const byId = new Map(records.map((x) => [String(x.id), x]));
  root.querySelectorAll(selector).forEach((row) => displayedRecords.set(row, { ...byId.get(row.dataset.id) }));
}

// ---------- 登录 ----------
function showLogin() { $("#book").hidden = true; $("#login").hidden = false; $("#pw").focus(); }
$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("#login-err").textContent = "";
  try {
    await api("/login", { method: "POST", body: { password: $("#pw").value } });
    $("#pw").value = ""; start();
  } catch (err) { $("#login-err").textContent = err instanceof AuthError ? "密码不对" : err.message; }
});

// ---------- 月历 ----------
async function loadMonth() {
  month = await api(`/month?ym=${ymOf(cursor)}`);
  renderMonth();
  if (openDate && openDate.startsWith(month.ym)) renderSheet();
}
function byDate(list) {
  const m = {};
  for (const x of list || []) (m[x.date] ||= []).push(x);
  return m;
}
function renderMonth() {
  const y = cursor.getFullYear(), mo = cursor.getMonth();
  $("#yr").firstChild.textContent = y;
  $("#mnum").textContent = mo + 1;
  $("#mname").textContent = MONTHS[mo];
  $("#days").textContent = "MY JOURNAL";

  const notes = byDate(month.notes), media = byDate(month.media), events = byDate(month.events);
  const decorated = new Set(month.decorated_pages || []);
  const lead = new Date(y, mo, 1).getDay();
  const n = new Date(y, mo + 1, 0).getDate();
  const cells = [];
  for (let i = 0; i < lead; i++) cells.push('<div class="d blank"></div>');
  for (let d = 1; d <= n; d++) {
    const key = `${y}-${pad(mo + 1)}-${pad(d)}`;
    const date = new Date(y, mo, d);
    const ev = events[key] || [];
    const ann = ev.some((e) => e.kind === "anniversary");
    const deco = decorated.has(`day:${key}`);
    const lines = [];
    for (const e of ev.filter((e) => e.kind !== "anniversary")) lines.push(`<div class="t ev">${e.time ? e.time + " " : ""}${esc(e.title)}</div>`);
    // 用户写的排前面
    const ns = (notes[key] || []).slice().sort((a, b) => (a.author === "human" ? -1 : 1) - (b.author === "human" ? -1 : 1));
    for (const x of ns) lines.push(`<div class="t ${x.author === "agent" ? "agent" : ""}">${esc(x.text)}</div>`);
    for (const x of media[key] || []) lines.push(`<div class="t md">${esc(x.title)}</div>`);
    const cap = window.innerWidth >= 700 ? 6 : 4;
    const shown = lines.slice(0, cap).join("") + (lines.length > cap ? `<div class="more">+${lines.length - cap}</div>` : "");
    const cls = ["d", date.getDay() === 0 && "sun", key === ymd(today) && "today"].filter(Boolean).join(" ");
    cells.push(`<div class="${cls}" data-date="${key}"><div class="num"><span>${d}</span><span class="ann">${deco ? "✿" : ""}${ann ? "♡" : ""}</span></div>${shown}</div>`);
  }
  while (cells.length % 7) cells.push('<div class="d blank"></div>');
  $("#grid").innerHTML = cells.join("");
  renderMonthGoals();
  renderSide();
}
$("#grid").addEventListener("click", (e) => {
  const c = e.target.closest(".d[data-date]");
  if (c) openDay(c.dataset.date);
});
$("#cover").onclick = () => openPage(`month:${ymOf(cursor)}`, `${ymOf(cursor)}-01`);
$("#prev").onclick = () => { cursor = new Date(cursor.getFullYear(), cursor.getMonth() - 1, 1); guard(loadMonth); };
$("#next").onclick = () => { cursor = new Date(cursor.getFullYear(), cursor.getMonth() + 1, 1); guard(loadMonth); };
// 左右滑翻月
let sx = null;
$("#grid").addEventListener("touchstart", (e) => { sx = e.touches[0].clientX; }, { passive: true });
$("#grid").addEventListener("touchend", (e) => {
  if (sx === null) return;
  const dx = e.changedTouches[0].clientX - sx; sx = null;
  if (Math.abs(dx) > 60) (dx < 0 ? $("#next") : $("#prev")).click();
});

// ---------- 目标（周 / 月） ----------
function goalRow(g) {
  const mark = g.status === "done" ? "✓" : g.status === "dropped" ? "–" : "";
  return `<div class="goal ${g.status}" data-id="${g.id}">
    <button class="ck" data-act="cycle" aria-label="切换状态">${mark}</button>
    <span class="txt">${esc(g.text)}</span>
    <span class="who">${who(g.author)}</span>
    <button class="x" data-act="del" aria-label="删除">×</button></div>`;
}
function goalList(list, period) {
  return (list.length ? list.map(goalRow).join("") : '<div class="empty">还没有</div>') +
    `<form class="add" data-period="${period}"><input placeholder="写一条…" maxlength="200"><button>add</button></form>`;
}
function renderMonthGoals() {
  const ym = month.ym;
  $("#mgoal").innerHTML = `In <span class="it">${MONTHS[cursor.getMonth()]}</span>, I <span class="it">need</span> to …
    <ul>${goalList(month.goals.month, ym)}</ul>`;
  rememberRows($("#mgoal"), ".goal", month.goals.month);
}
function currentWeekKey() {
  const wk = isoWeek(today);
  return month.goals.weeks[wk] ? wk : Object.keys(month.goals.weeks)[0];
}
function renderSide() {
  const wk = currentWeekKey();
  $("#side").innerHTML = `<div class="block"><h5>This week · ${wk.slice(5)}</h5>${goalList(month.goals.weeks[wk] || [], wk)}</div>`;
  rememberRows($("#side"), ".goal", month.goals.weeks[wk] || []);
}
function renderWeek() {
  const weeks = month.goals.weeks;
  $("#tab-week").innerHTML = `<div class="sec-h"><span class="n">${cursor.getMonth() + 1}</span><span class="it">weekly</span></div>` +
    Object.keys(weeks).map((wk) => `<div class="block"><h5>${wk.slice(5)}${wk === isoWeek(today) ? " · this week" : ""}</h5>${goalList(weeks[wk], wk)}</div>`).join("");
  rememberRows($("#tab-week"), ".goal", Object.values(weeks).flat());
}
function renderSeen() {
  const list = (month.media || []).slice().sort((a, b) => a.date.localeCompare(b.date));
  $("#tab-seen").innerHTML = `<div class="sec-h"><span class="n">${cursor.getMonth() + 1}</span><span class="it">seen</span></div><div class="block">` +
    (list.length ? list.map((m) => `<div class="seen-row"><span>${esc(m.title)}</span><small>${KIND[m.kind] || ""} · ${m.date.slice(5).replace("-", ".")}</small></div>`).join("")
      : '<div class="empty">这个月还没记看过的书和剧。点开某一天就能加。</div>') + "</div>";
}
const STATUS_NEXT = { open: "done", done: "dropped", dropped: "open" };
document.addEventListener("click", (e) => {
  const btn = e.target.closest(".goal [data-act]");
  if (!btn) return;
  const row = btn.closest(".goal"), id = Number(row.dataset.id);
  const g = displayedRecords.get(row);
  guard(async () => {
    if (btn.dataset.act === "cycle") await api(`/goals/${id}`, { method: "PATCH", version: g.updated_at, body: { status: STATUS_NEXT[g.status] } });
    else if (confirm(`删掉「${g.text}」？`)) await api(`/goals/${id}`, { method: "DELETE", version: g.updated_at });
    await refresh();
  });
});
document.addEventListener("submit", (e) => {
  const f = e.target.closest("form.add");
  if (!f) return;
  e.preventDefault();
  const text = f.querySelector("input").value.trim();
  if (!text) return;
  const period = f.dataset.period;
  guard(async () => {
    await api("/goals", { method: "POST", body: { scope: period.includes("W") ? "week" : "month", period, text } });
    await refresh();
  });
});

// ---------- 某一天 ----------
function openDay(date) {
  openDate = date;
  renderSheet();
  $("#sheet").classList.add("on"); $("#scrim").classList.add("on");
  $("#sheet").setAttribute("aria-hidden", "false");
}
function closeDay() {
  openDate = null;
  $("#sheet").classList.remove("on"); $("#scrim").classList.remove("on");
  $("#sheet").setAttribute("aria-hidden", "true");
}
$("#scrim").onclick = closeDay;
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDay(); });

function entry(kind, x, html) {
  return `<div class="entry ${x.author}" data-kind="${kind}" data-id="${x.id}">
    <span class="who">${who(x.author)}</span><div class="body">${html}</div>
    <button class="x" data-act="del" aria-label="删除">×</button></div>`;
}
function renderSheet() {
  if (sheetDate === openDate && $("#sheet-in .body[contenteditable=true]")) return;
  sheetDate = openDate;
  const [y, m, d] = openDate.split("-").map(Number);
  const date = new Date(y, m - 1, d);
  const pick = (list) => (list || []).filter((x) => x.date === openDate);
  const notes = pick(month.notes).map((x) => noteDrafts.get(String(x.id))?.record || x);
  // 冲突或条目已被删除时，刷新仍保留草稿及其打开时的版本。
  for (const [id, draft] of noteDrafts) {
    if (draft.record.date === openDate && !notes.some((x) => String(x.id) === id)) notes.push(draft.record);
  }
  notes.sort((a, b) => (a.author === "human" ? -1 : 1) - (b.author === "human" ? -1 : 1));
  const events = pick(month.events), media = pick(month.media);
  $("#sheet-in").innerHTML = `
    <h4>${pad(m)}.${pad(d)}<span class="it">${WK[date.getDay()]}</span><button class="close" data-act="close">close</button></h4>

    <h5>PAGE</h5>
    ${(month.decorated_pages || []).includes(`day:${openDate}`)
      ? `<div class="page mini" data-act="deco" role="button" aria-label="装修这一页"></div>`
      : '<button class="deco-btn" data-act="deco">✿ 装修这一页</button>'}

    <h5>DAY</h5>
    ${notes.map((x) => entry("notes", x, esc(noteDrafts.get(String(x.id))?.text ?? x.text))).join("")}
    <form data-new="notes"><textarea placeholder="今天，写一句…" maxlength="500"></textarea>
      <div class="row" style="border:0;justify-content:flex-end"><button class="save">save</button></div></form>

    <h5>PLANS</h5>
    ${events.map((x) => entry("events", x, `${x.kind === "anniversary" ? "♡ " : ""}${x.time ? x.time + " " : ""}${esc(x.title)}${x.place ? ` <span style="color:var(--w2)">@ ${esc(x.place)}</span>` : ""}`)).join("")}
    <form data-new="events" class="row"><input class="short" name="time" type="time"><input name="title" placeholder="安排…"><input name="place" class="short" placeholder="在哪"><button class="save">add</button></form>

    <h5>SEEN</h5>
    ${media.map((x) => entry("media", x, `${esc(x.title)} <span style="color:var(--w2)">${KIND[x.kind] || ""}</span>`)).join("")}
    <form data-new="media" class="row"><select name="kind"><option value="book">书</option><option value="film">电影</option><option value="series">剧</option><option value="show">综艺</option><option value="other">其他</option></select><input name="title" placeholder="看过的…"><button class="save">add</button></form>`;
  rememberRows($("#sheet-in"), ".entry[data-kind=notes]", notes);
  rememberRows($("#sheet-in"), ".entry[data-kind=events]", events);
  rememberRows($("#sheet-in"), ".entry[data-kind=media]", media);
  const mini = $("#sheet-in .page.mini");
  if (mini) { const d = openDate; guard(async () => { const st = await PAGE.load(`day:${d}`); if (mini.isConnected) PAGE.render(mini, st); }); }
}
function openPage(page, date) {
  guard(() => PAGE.open(page, date, (saved) => { guard(refresh); }));
}
$("#sheet-in").addEventListener("click", (e) => {
  const b = e.target.closest("[data-act]");
  if (!b) return;
  if (b.dataset.act === "close") return closeDay();
  if (b.dataset.act === "deco") return openPage(`day:${openDate}`, openDate);
  if (b.dataset.act === "del") {
    const row = b.closest(".entry"), record = displayedRecords.get(row);
    if (!confirm("删掉这条？")) return;
    guard(async () => {
      await api(`/${row.dataset.kind}/${row.dataset.id}`, { method: "DELETE", version: record.updated_at });
      if (row.dataset.kind === "notes") noteDrafts.delete(row.dataset.id);
      await refresh();
    });
  }
});
// 点一下日记那一行就能直接改
$("#sheet-in").addEventListener("click", (e) => {
  const body = e.target.closest(".entry[data-kind=notes] .body");
  if (!body || body.isContentEditable) return;
  const row = body.closest(".entry"), id = row.dataset.id;
  let draft = noteDrafts.get(id);
  if (!draft) {
    draft = { record: { ...displayedRecords.get(row) }, text: body.innerText };
    noteDrafts.set(id, draft);
  }
  if (draft.saving) return;
  body.contentEditable = "true"; body.focus();
  const remember = () => { draft.text = body.innerText; };
  body.addEventListener("input", remember);
  body.addEventListener("blur", () => {
    body.contentEditable = "false";
    body.removeEventListener("input", remember);
    remember();
    const text = draft.text.trim(), old = draft.record;
    if (!text || text === old.text) { noteDrafts.delete(id); body.textContent = old.text; return; }
    guard(async () => {
      draft.saving = true;
      try {
        const updated = await api(`/notes/${id}`, { method: "PATCH", version: old.updated_at, body: { text } });
        noteDrafts.delete(id);
        displayedRecords.set(row, { ...updated });
        body.textContent = updated.text;
        await refresh();
      } finally { draft.saving = false; }
    });
  }, { once: true });
});
$("#sheet-in").addEventListener("submit", (e) => {
  e.preventDefault();
  const f = e.target, kind = f.dataset.new;
  const val = (n) => f.querySelector(`[name=${n}]`)?.value.trim() || null;
  let body;
  if (kind === "notes") { const t = f.querySelector("textarea").value.trim(); if (!t) return; body = { date: openDate, text: t }; }
  if (kind === "events") { if (!val("title")) return; body = { date: openDate, title: val("title"), time: val("time"), place: val("place") }; }
  if (kind === "media") { if (!val("title")) return; body = { date: openDate, kind: val("kind"), title: val("title") }; }
  guard(async () => { await api(`/${kind}`, { method: "POST", body }); await refresh(); });
});

// ---------- 切换 ----------
$("#tabs").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-tab]");
  if (!b) return;
  tab = b.dataset.tab;
  document.querySelectorAll("#tabs button").forEach((x) => x.classList.toggle("on", x === b));
  for (const t of ["month", "week", "seen"]) $(`#tab-${t}`).hidden = t !== tab;
  renderTab();
});
function renderTab() { if (tab === "week") renderWeek(); if (tab === "seen") renderSeen(); }
async function refresh() { await loadMonth(); renderTab(); }
let lastW = window.innerWidth;
window.addEventListener("resize", () => { if ((lastW >= 700) !== (window.innerWidth >= 700) && month) renderMonth(); lastW = window.innerWidth; });

// ---------- 启动 ----------
async function start() {
  try {
    await api("/me");
    $("#login").hidden = true; $("#book").hidden = false;
    await refresh();
  } catch (e) { if (e instanceof AuthError) showLogin(); else toast(e.message); }
}
start();
if (!window.TECHO_DEMO && "serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
