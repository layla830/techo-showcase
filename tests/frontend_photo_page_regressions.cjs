"use strict";

// No browser packages or network: exercise page.js with a small DOM and fetch mock.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const vm = require("node:vm");

const root = path.resolve(__dirname, "..");
const pageSource = fs.readFileSync(path.join(root, "frontend", "page.js"), "utf8");
const appSource = fs.readFileSync(path.join(root, "frontend", "app.js"), "utf8");
// Use the real api/guard/AuthError so the 401 assertion includes the login path.
const networkSource = appSource.slice(appSource.indexOf("class AuthError"), appSource.indexOf("let toastTimer")) +
  appSource.slice(appSource.indexOf("async function guard"), appSource.indexOf("// ---------- 状态 ----------"));
const A = "day:2026-11-08", B = "day:2026-11-09";
const HASH = "a3f9c2e1b07d";

class MockEvent {
  constructor(type, options = {}) { this.type = type; Object.assign(this, options); }
  preventDefault() { this.defaultPrevented = true; }
}

class Element {
  constructor(tag) {
    this.tagName = tag.toLowerCase(); this.children = []; this.parentNode = null;
    this.attributes = {}; this.dataset = {}; this.style = {}; this.listeners = new Map();
    this.value = ""; this.hidden = false; this.inert = false;
  }
  get className() { return this.attributes.class || ""; }
  set className(value) { this.attributes.class = value; }
  get classList() {
    const el = this;
    return {
      contains(c) { return el.className.split(/\s+/).includes(c); },
      toggle(c, force) {
        const classes = new Set(el.className.split(/\s+/).filter(Boolean));
        const on = force === undefined ? !classes.has(c) : force;
        if (on) classes.add(c); else classes.delete(c);
        el.className = [...classes].join(" "); return on;
      },
      add(c) { this.toggle(c, true); },
      remove(c) { this.toggle(c, false); },
    };
  }
  get isConnected() { return this.tagName === "body" || !!this.parentNode?.isConnected; }
  setAttribute(name, value) {
    this.attributes[name] = value;
    if (name.startsWith("data-")) this.dataset[name.slice(5)] = value;
    if (name === "hidden") this.hidden = true;
    if (name === "value") this.value = value;
  }
  appendChild(child) { child.remove(); this.children.push(child); child.parentNode = this; return child; }
  remove() {
    if (this.parentNode) this.parentNode.children = this.parentNode.children.filter((x) => x !== this);
    this.parentNode = null;
  }
  set innerHTML(html) {
    for (const child of this.children) child.parentNode = null;
    this.children = [];
    const stack = [this];
    const tags = /<\/?([a-z][a-z\d-]*)([^<>]*?)>/gi;
    for (const match of html.matchAll(tags)) {
      if (match[0].startsWith("</")) { stack.pop(); continue; }
      const el = new Element(match[1]);
      for (const attr of match[2].matchAll(/([^\s=\/]+)(?:="([^"]*)")?/g)) el.setAttribute(attr[1], attr[2] ?? "");
      stack.at(-1).appendChild(el);
      if (!["img", "input", "br"].includes(el.tagName) && !match[0].endsWith("/>")) stack.push(el);
    }
  }
  matchesSimple(selector) {
    const tag = selector.match(/^[a-z][\w-]*/i)?.[0];
    if (tag && this.tagName !== tag) return false;
    for (const c of selector.matchAll(/\.([\w-]+)/g)) if (!this.classList.contains(c[1])) return false;
    for (const attr of selector.matchAll(/\[([^\]=]+)(?:=["']?([^\]"']+)["']?)?\]/g)) {
      const value = attr[1].startsWith("data-") ? this.dataset[attr[1].slice(5)] : this.attributes[attr[1]];
      if (value === undefined || (attr[2] !== undefined && value !== attr[2])) return false;
    }
    return true;
  }
  matches(selector) {
    return selector.split(",").some((part) => {
      const parts = part.trim().split(/\s+/);
      if (!this.matchesSimple(parts.pop())) return false;
      let ancestor = this.parentNode;
      while (parts.length) {
        const wanted = parts.pop();
        while (ancestor && !ancestor.matchesSimple(wanted)) ancestor = ancestor.parentNode;
        if (!ancestor) return false;
        ancestor = ancestor.parentNode;
      }
      return true;
    });
  }
  closest(selector) { for (let el = this; el; el = el.parentNode) if (el.matches(selector)) return el; return null; }
  querySelectorAll(selector) {
    const result = [];
    const walk = (el) => { for (const child of el.children) { if (child.matches(selector)) result.push(child); walk(child); } };
    walk(this); return result;
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  addEventListener(type, listener) {
    if (!this.listeners.has(type)) this.listeners.set(type, []);
    this.listeners.get(type).push(listener);
  }
  dispatchEvent(event) {
    event.target ||= this;
    for (const listener of this.listeners.get(event.type) || []) listener(event);
    if (this[`on${event.type}`]) this[`on${event.type}`](event);
    if (event.bubbles && this.parentNode) this.parentNode.dispatchEvent(event);
    return !event.defaultPrevented;
  }
  setPointerCapture() {}
  getBoundingClientRect() { return { width: 300, height: 400, left: 0, top: 0 }; }
  getContext() {
    this.contextReads = (this.contextReads || 0) + 1;
    return Object.fromEntries(["setTransform", "beginPath", "arc", "fill", "moveTo", "lineTo", "stroke", "fillRect", "drawImage"].map((key) => [key, () => {}]));
  }
  toBlob(callback) { callback(new Blob(["compressed photo"], { type: "image/jpeg" })); }
}

function deferred() {
  let resolve, reject;
  const promise = new Promise((ok, bad) => { resolve = ok; reject = bad; });
  return { promise, resolve, reject };
}
function response(status, data = {}) {
  return { status, ok: status >= 200 && status < 300, json: async () => data, blob: async () => new Blob(["photo"], { type: "image/webp" }) };
}
const settle = async () => { for (let i = 0; i < 3; i++) await new Promise(setImmediate); };
function item(item_type, fields = {}) {
  return { item_type, ref: item_type === "photo" ? "12" : "hand", text: item_type === "text" ? "hello" : null,
    color: null, x: 0.5, y: 0.45, scale: 1, rotation: 0, z: 0, ...fields };
}

function fixture(items = [], photos = []) {
  const body = new Element("body");
  const document = { body, createElement: (tag) => new Element(tag), querySelector: (s) => body.querySelector(s) };
  const h = { calls: [], puts: [], uploads: [], closed: [], toasts: [], logins: 0, created: [], revoked: [], month: { photos } };
  const sandbox = {
    document, API: "api/v1", month: h.month, Blob, FormData, CustomEvent: MockEvent,
    $: (selector, el = document) => el.querySelector(selector),
    esc: (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])),
    toast: (message) => h.toasts.push(message), showLogin: () => h.logins++, confirm: () => true,
    STICKERS: { pack: { tape: { w: 12 } }, src: () => "data:image/svg+xml,mock", EMOJI: ["flower"] },
    window: { devicePixelRatio: 1 }, requestAnimationFrame: (callback) => callback(),
    addEventListener() {}, removeEventListener() {},
    URL: { createObjectURL(blob) { const url = `blob:mock-${h.created.length}`; h.created.push({ url, blob }); return url; },
      revokeObjectURL(url) { h.revoked.push(url); } },
    createImageBitmap: (...args) => h.bitmap ? h.bitmap(...args) : Promise.resolve({ width: 1600, height: 1200 }),
    fetch: async (url, options = {}) => {
      const method = options.method || "GET";
      const call = { url, ...options, method }; h.calls.push(call);
      if (url.startsWith("api/v1/decorations?")) {
        if (method === "GET") return response(200, { version: null, items: JSON.parse(JSON.stringify(items)) });
        assert.equal(method, "PUT");
        call.data = JSON.parse(call.body); h.puts.push(call);
        return h.put ? h.put(call) : response(200, { version: `v${h.puts.length}` });
      }
      if (url.startsWith("api/v1/strokes?")) {
        if (method === "GET") return response(200, { strokes: [] });
        if (h.strokePost) return h.strokePost(call);
        return response(201, { strokes: [{ ...JSON.parse(call.body).strokes[0], id: 31 }] });
      }
      if (url.startsWith("api/v1/strokes/")) return h.strokeDelete ? h.strokeDelete(call) : response(200, { ok: true });
      if (url === "api/v1/photos" && method === "POST") {
        h.uploads.push(call);
        return h.upload ? h.upload(call) : response(201, { id: 13, hash: HASH });
      }
      if (url.startsWith("api/v1/photos/")) return h.photo ? h.photo(call) : response(200);
      throw new Error(`Unexpected mock request: ${method} ${url}`);
    },
  };
  vm.createContext(sandbox);
  vm.runInContext(`${networkSource}\n${pageSource}\nglobalThis.pageUnderTest = PAGE;`, sandbox, { filename: "page.js" });
  h.page = sandbox.pageUnderTest;
  h.root = () => body.querySelector(".editor");
  h.open = async (page = A) => { await h.page.open(page, page.slice(4), (saved) => h.closed.push(saved)); await settle(); return h.root(); };
  h.click = (data) => {
    const button = new Element("button"); Object.assign(button.dataset, data);
    h.root().dispatchEvent(new MockEvent("click", { target: button }));
  };
  h.emit = (el, type, options = {}) => el.dispatchEvent(new MockEvent(type, { target: el, pointerId: 1, clientX: 150, clientY: 200, ...options }));
  h.file = () => { h.click({ t: "photo" }); return h.root().querySelector("input[type=file]"); };
  h.startUpload = () => { const file = h.file(); file.files = [{}]; file.onchange(); return file; };
  h.preview = (thumb = true) => {
    const el = document.createElement("div"); body.appendChild(el);
    h.page.render(el, { items: JSON.parse(JSON.stringify(items)), strokes: [] }, thumb); return el;
  };
  return h;
}

test("done locks clicks, forms, file input, gestures, close and duplicate saves until the PUT completes", async () => {
  const h = fixture([item("text")]);
  const editor = await h.open();
  const file = h.file();
  h.click({ t: "text" });
  const form = editor.querySelector("form[data-f=text]");
  form.querySelector("input").value = "saved addition";
  form.onsubmit(new MockEvent("submit"));
  const stage = editor.querySelector(".page"), node = stage.querySelector(".pi");
  h.emit(stage, "pointerdown", { target: node });
  const pending = deferred(); h.put = () => pending.promise;
  h.click({ a: "done" });
  assert.equal(h.puts.length, 1);
  assert.equal(editor.inert, true);
  const position = JSON.stringify(node.style);
  for (const data of [{ a: "done" }, { a: "cancel" }, { a: "del" }, { a: "front" }, { a: "cap" }, { a: "undo" },
    { s: "emoji:flower" }, { c: "#a9c2e6" }, { w: "0.012" }, { t: "pen" }]) h.click(data);
  form.querySelector("input").value = "must not be added";
  form.onsubmit(new MockEvent("submit"));
  file.files = [{}]; file.onchange();
  h.emit(stage, "pointermove", { clientX: 260, clientY: 300 });
  h.emit(stage, "wheel", { deltaY: 200 });
  h.emit(stage, "wheel", { deltaY: 200, shiftKey: true });
  h.emit(stage, "pointerup");
  h.emit(stage, "pointerdown", { target: node });
  h.emit(stage, "pointermove", { clientX: 50 });
  assert.equal(JSON.stringify(node.style), position);
  assert.equal(stage.querySelectorAll(".pi").length, 2);
  assert.equal(h.root(), editor);
  assert.equal(h.uploads.length, 0);
  assert.equal(h.puts.length, 1);
  assert.equal(h.closed.length, 0);
  pending.resolve(response(200, { version: "v1" })); await settle();
  assert.equal(h.root(), null);
  assert.deepEqual(h.closed, [true]);
});

test("failed save unlocks the same dirty editor and permits a complete retry", async () => {
  const h = fixture(); const editor = await h.open();
  h.click({ s: "emoji:flower" });
  h.put = () => response(503, { error: { message: "try again" } });
  h.click({ a: "done" }); await settle();
  assert.equal(h.root(), editor); assert.equal(editor.inert, false); assert.deepEqual(h.closed, []);
  h.click({ s: "emoji:flower" }); h.put = null;
  h.click({ a: "done" }); await settle();
  assert.equal(h.puts[1].data.items.length, 2); assert.deepEqual(h.closed, [true]);
});

test("upload completing during a PUT remains dirty, uses its hash, and is included by the next done", async () => {
  const h = fixture(); const editor = await h.open();
  const upload = deferred(); h.upload = () => upload.promise;
  h.startUpload(); await settle(); assert.equal(h.uploads.length, 1);
  h.click({ s: "emoji:flower" });
  const save = deferred(); h.put = () => save.promise;
  h.click({ a: "done" });
  upload.resolve(response(201, { id: 13, hash: HASH })); await settle();
  assert.equal(editor.querySelectorAll(".pi-photo").length, 1);
  assert.ok(h.calls.some((c) => c.url === `api/v1/photos/13?size=full&h=${HASH}`));
  save.resolve(response(200, { version: "v1" })); await settle();
  assert.equal(h.root(), editor); assert.equal(editor.inert, false); assert.deepEqual(h.closed, []);
  h.put = null; h.click({ a: "done" }); await settle();
  const saved = h.puts[1].data;
  assert.equal(saved.version, "v1"); assert.equal(saved.items.length, 2);
  assert.equal(saved.items[1].ref, "13");
  assert.deepEqual(Object.keys(saved.items[1]).sort(), ["color", "item_type", "ref", "rotation", "scale", "text", "x", "y", "z"]);
  assert.deepEqual(h.closed, [true]);
});

for (const failure of ["503", "network", "decode", "blob"]) {
  test(`${failure} image failure preserves the photo reference in the next saved page`, async () => {
    const h = fixture([item("photo")]);
    if (failure === "503") h.photo = () => response(503);
    if (failure === "network") h.photo = () => Promise.reject(new Error("offline"));
    if (failure === "blob") h.photo = () => ({ ...response(200), blob: async () => { throw new Error("interrupted body"); } });
    const editor = await h.open();
    if (failure === "decode") editor.querySelector(".pi-photo img").onerror();
    assert.equal(editor.querySelectorAll(".pi-photo").length, 1);
    assert.equal(h.toasts.length, 0); assert.equal(h.logins, 0);
    h.click({ s: "emoji:flower" }); h.click({ a: "done" }); await settle();
    assert.ok(h.puts[0].data.items.some((it) => it.item_type === "photo" && it.ref === "12"));
    assert.equal(h.revoked.length, h.created.length);
  });
}

test("only confirmed HTTP 404 removes the item and persists that removal", async () => {
  const h = fixture([item("photo")]); h.photo = () => response(404);
  const editor = await h.open();
  assert.equal(editor.querySelectorAll(".pi-photo").length, 0);
  assert.equal(h.toasts.length, 1); assert.equal(h.logins, 0);
  h.click({ a: "done" }); await settle();
  assert.deepEqual(h.puts[0].data.items, []); assert.deepEqual(h.closed, [true]);
});

test("photo HTTP 401 invokes the existing login handler and retains the item", async () => {
  const h = fixture([item("photo")]); h.photo = () => response(401);
  const editor = await h.open();
  assert.equal(h.logins, 1); assert.equal(h.toasts.length, 0);
  assert.equal(editor.querySelectorAll(".pi-photo").length, 1);
  h.click({ s: "emoji:flower" }); h.click({ a: "done" }); await settle();
  assert.ok(h.puts[0].data.items.some((it) => it.item_type === "photo"));
});

test("404 arriving during a PUT does not clear the later removal or close the dirty editor", async () => {
  const h = fixture([item("photo")]);
  const photo = deferred(); h.photo = () => photo.promise;
  const editor = await h.open(); h.click({ s: "emoji:flower" });
  const save = deferred(); h.put = () => save.promise;
  h.click({ a: "done" });
  photo.resolve(response(404)); await settle();
  save.resolve(response(200, { version: "v1" })); await settle();
  assert.equal(h.root(), editor); assert.equal(editor.inert, false);
  assert.equal(h.puts[0].data.items.length, 2); assert.deepEqual(h.closed, []);
  h.put = null; h.click({ a: "done" }); await settle();
  assert.equal(h.puts[1].data.version, "v1");
  assert.equal(h.puts[1].data.items.length, 1);
  assert.equal(h.puts[1].data.items[0].item_type, "sticker");
});

for (const destination of [B, A, null]) {
  test(`closed editor's upload is ignored after ${destination ? `opening ${destination}` : "closing without reopening"}`, async () => {
    const h = fixture(); await h.open();
    const pending = deferred(); h.upload = () => pending.promise;
    const oldInput = h.startUpload(); await settle();
    assert.equal(h.uploads[0].body.get("date"), A.slice(4));
    h.click({ a: "cancel" });
    const nextEditor = destination ? await h.open(destination) : null;
    // Detached input handlers must not launch uploads into a later editor either.
    oldInput.files = [{}]; oldInput.onchange();
    pending.resolve(response(201, { id: 13, hash: HASH })); await settle();
    assert.equal(h.uploads.length, 1);
    assert.equal(h.root(), nextEditor);
    assert.ok(!h.toasts.includes("贴上了"));
    assert.equal(h.calls.filter((c) => c.url.startsWith("api/v1/photos/")).length, 0);
    if (nextEditor) {
      assert.equal(nextEditor.querySelectorAll(".pi-photo").length, 0);
      h.click({ s: "emoji:flower" }); h.click({ a: "done" }); await settle();
      assert.equal(h.puts[0].url, `api/v1/decorations?page=${encodeURIComponent(destination)}`);
      assert.equal(h.puts[0].data.items.length, 1);
      assert.equal(h.puts[0].data.items[0].item_type, "sticker");
    }
  });
}

test("upload compression started on A retains A's date after B opens", async () => {
  const h = fixture(); await h.open();
  const bitmap = deferred(); h.bitmap = () => bitmap.promise;
  h.startUpload(); h.click({ a: "cancel" }); const editor = await h.open(B);
  bitmap.resolve({ width: 1600, height: 1200 }); await settle();
  assert.equal(h.uploads[0].body.get("date"), A.slice(4));
  assert.equal(editor.querySelectorAll(".pi-photo").length, 0);
});

test("known full and thumbnail hashes produce content-specific URLs, including a restored id's new hash", async () => {
  const h = fixture([item("photo")], [{ id: 12, hash: HASH }]);
  const editor = await h.open(); const mini = h.preview(); await settle();
  const reads = h.calls.filter((c) => c.url.startsWith("api/v1/photos/"));
  assert.deepEqual(reads.map((c) => c.url), [`api/v1/photos/12?size=full&h=${HASH}`, `api/v1/photos/12?size=thumb&h=${HASH}`]);
  assert.ok(reads.every((c) => c.cache === "default" && c.credentials === "same-origin"));
  const full = editor.querySelector(".pi-photo img"), thumb = mini.querySelector("img");
  assert.match(full.src, /^blob:mock-/); assert.match(thumb.src, /^blob:mock-/);
  full.onload(); thumb.onload(); assert.equal(h.revoked.length, 2);
  const restoredHash = "b4f9c2e1b07d"; h.month.photos = [{ id: 12, hash: restoredHash }];
  h.page.render(mini, { items: [item("photo")], strokes: [] }); await settle();
  assert.equal(h.calls.at(-1).url, `api/v1/photos/12?size=thumb&h=${restoredHash}`);
});

test("unknown hashes bypass bare-id caching for both sizes and release blob URLs on replacement and close", async () => {
  const h = fixture([item("photo")]);
  const editor = await h.open(); const mini = h.preview(); await settle();
  const reads = h.calls.filter((c) => c.url.startsWith("api/v1/photos/"));
  assert.deepEqual(reads.map((c) => c.url), ["api/v1/photos/12?size=full", "api/v1/photos/12?size=thumb"]);
  assert.ok(reads.every((c) => c.cache === "no-store" && c.credentials === "same-origin"));
  assert.match(editor.querySelector("img").src, /^blob:mock-/);
  const thumbnailURL = mini.querySelector("img").src;
  h.page.render(mini, { items: [], strokes: [] });
  assert.ok(h.revoked.includes(thumbnailURL));
  const fullURL = editor.querySelector("img").src;
  h.click({ a: "cancel" });
  assert.ok(h.revoked.includes(fullURL));
  assert.equal(new Set(h.revoked).size, h.created.length);
});

test("photo blob URLs are released when captions remount or items are deleted", async () => {
  const h = fixture([item("photo")]); const editor = await h.open();
  const stage = editor.querySelector(".page"), photo = editor.querySelector(".pi-photo");
  h.emit(stage, "pointerdown", { target: photo }); h.emit(stage, "pointerup");
  const firstURL = photo.querySelector("img").src;
  editor.querySelector(".cap input").value = "caption";
  h.click({ a: "cap" }); await settle();
  assert.ok(h.revoked.includes(firstURL));
  const secondURL = editor.querySelector(".pi-photo img").src;
  h.click({ a: "del" });
  assert.ok(h.revoked.includes(secondURL)); assert.equal(h.created.length, h.revoked.length);
});

test("done waits for every pending stroke request and stays open on failure without retrying", async () => {
  for (const method of ["POST", "DELETE"]) {
    for (const outcome of ["success", "failure"]) {
      const h = fixture(); const editor = await h.open();
      h.click({ s: "emoji:flower" }); h.click({ t: "pen" });
      const stage = editor.querySelector(".page");
      const pending = deferred();
      if (method === "POST") {
        const first = deferred(); let posted = 0;
        h.strokePost = () => (++posted === 1 ? first.promise : pending.promise);
        h.emit(stage, "pointerdown"); h.emit(stage, "pointerup");
        // done must also finish and await a stroke whose pointer is still down.
        h.emit(stage, "pointerdown"); h.click({ a: "done" });
        await settle();
        assert.equal(h.puts.length, 0); assert.equal(h.root(), editor);
        first.resolve(response(201, { strokes: [{ id: 31 }] })); await settle();
      } else {
        h.emit(stage, "pointerdown"); h.emit(stage, "pointerup"); await settle();
        h.strokeDelete = () => pending.promise;
        h.click({ a: "undo" }); h.click({ a: "done" }); await settle();
      }
      assert.equal(h.root(), editor); assert.equal(editor.inert, true);
      assert.equal(h.puts.length, 0); assert.deepEqual(h.closed, []);
      h.click({ a: "done" }); h.click({ a: "cancel" });
      const requestCount = h.calls.filter((c) => c.method === method && c.url.startsWith("api/v1/strokes")).length;
      assert.equal(requestCount, method === "POST" ? 2 : 1);
      if (outcome === "failure") pending.reject(new Error(`stroke ${method} failed`));
      else pending.resolve(response(method === "POST" ? 201 : 200, { strokes: [{ id: 32 }], ok: true }));
      await settle();
      if (outcome === "failure") {
        assert.equal(h.root(), editor); assert.equal(editor.inert, false);
        assert.equal(h.puts.length, 0); assert.deepEqual(h.closed, []);
        assert.ok(h.toasts.includes(`stroke ${method} failed`));
      } else {
        assert.equal(h.root(), null); assert.deepEqual(h.closed, [true]);
        assert.equal(h.puts.length, 1); assert.equal(h.puts[0].data.items.length, 1);
      }
      assert.equal(h.calls.filter((c) => c.method === method && c.url.startsWith("api/v1/strokes")).length, requestCount);
    }
  }
});

test("old stroke POST and undo callbacks cannot change mine or redraw a reopened instance of A", async () => {
  for (const method of ["POST", "DELETE"]) {
    for (const outcome of ["success", "failure"]) {
      const h = fixture(); const oldEditor = await h.open(A);
      h.click({ t: "pen" }); const oldStage = oldEditor.querySelector(".page");
      const pending = deferred();
      if (method === "POST") h.strokePost = () => pending.promise;
      h.emit(oldStage, "pointerdown"); h.emit(oldStage, "pointerup"); await settle();
      if (method === "DELETE") {
        h.strokeDelete = () => pending.promise;
        h.click({ a: "undo" }); await settle();
      }
      h.click({ a: "cancel" });
      const newEditor = await h.open(A), canvas = newEditor.querySelector(".ink");
      const redraws = canvas.contextReads;
      assert.notEqual(newEditor, oldEditor);
      if (outcome === "failure") pending.reject(new Error(`old ${method} failed`));
      else pending.resolve(response(method === "POST" ? 201 : 200, { strokes: [{ id: 31 }], ok: true }));
      await settle();
      assert.equal(h.root(), newEditor); assert.equal(canvas.contextReads, redraws);
      const deletes = h.calls.filter((c) => c.method === "DELETE").length;
      h.click({ a: "undo" }); await settle();
      assert.equal(h.calls.filter((c) => c.method === "DELETE").length, deletes);
      assert.ok(h.toasts.includes("这次没有可以撤销的笔画"));
      assert.equal(canvas.contextReads, redraws);
    }
  }
});

for (const phase of ["response", "body"]) {
  test(`photo ${phase} completing after close creates no object URL`, async () => {
    const h = fixture([item("photo")]); const pending = deferred();
    h.photo = () => phase === "response" ? pending.promise : { ...response(200), blob: () => pending.promise };
    await h.open(); h.click({ a: "cancel" });
    pending.resolve(phase === "response" ? response(200) : new Blob(["late"])); await settle();
    assert.equal(h.created.length, 0); assert.equal(h.toasts.length, 0);
  });
}
