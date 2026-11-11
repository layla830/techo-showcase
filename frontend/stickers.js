"use strict";
// techo 贴纸包 · AI 助手画的
// 每张贴纸：w = 基础宽度（页宽的百分之几），svg = 图。后端只存 "pack:<名字>"。
// 名字一旦上线就别改，改了旧页上的贴纸就认不出来了；要换图就换 svg。

const STICKERS = (() => {
  const W = "#f4f2ee";
  const line = (sw = 3) => `fill="none" stroke="${W}" stroke-width="${sw}" stroke-linecap="round" stroke-linejoin="round"`;
  const svg = (vb, body) => `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${vb}">${body}</svg>`;

  // 纸胶带：两头撕出来的锯齿
  function tape(name, fill, pattern) {
    const w = 200, h = 44, n = 7, step = h / n;
    const pts = [];
    for (let i = 0; i <= n; i++) pts.push(`${w - (i % 2 ? 5 : 0)},${(i * step).toFixed(1)}`);
    for (let i = n; i >= 0; i--) pts.push(`${i % 2 ? 0 : 5},${(i * step).toFixed(1)}`);
    const shape = `points="${pts.join(" ")}"`;
    const pat = {
      plain: "",
      stripe: `<pattern id="p" width="14" height="14" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="6" height="14" fill="#fff" opacity=".45"/></pattern>`,
      dot: `<pattern id="p" width="16" height="16" patternUnits="userSpaceOnUse"><circle cx="8" cy="8" r="2.4" fill="#fff" opacity=".6"/></pattern>`,
      grid: `<pattern id="p" width="11" height="11" patternUnits="userSpaceOnUse"><path d="M11 0H0v11" fill="none" stroke="#fff" stroke-width="1" opacity=".5"/></pattern>`,
    }[pattern];
    return [name, { w: 34, svg: svg("200 44", `${pat ? `<defs>${pat}</defs>` : ""}<polygon ${shape} fill="${fill}" opacity=".82"/>${pat ? `<polygon ${shape} fill="url(#p)"/>` : ""}`) }];
  }

  const petals = (n, body) => Array.from({ length: n }, (_, i) => `<g transform="rotate(${(360 / n) * i} 50 50)">${body}</g>`).join("");

  const pack = Object.fromEntries([
    tape("tape-sage", "#a9b8a0", "plain"),
    tape("tape-blue", "#a9c2e6", "stripe"),
    tape("tape-kraft", "#c8b08a", "grid"),
    tape("tape-blush", "#e3bdb6", "dot"),

    ["heart", { w: 12, svg: svg("100 100", `<path ${line()} d="M50 84C22 64 11 47 11 33c0-11 8-20 19-20 8 0 15 5 20 13 5-8 12-13 20-13 11 0 19 9 19 20 0 14-11 31-39 51z"/>`) }],
    ["heart-fill", { w: 10, svg: svg("100 100", `<path fill="#e9b8b3" d="M50 84C22 64 11 47 11 33c0-11 8-20 19-20 8 0 15 5 20 13 5-8 12-13 20-13 11 0 19 9 19 20 0 14-11 31-39 51z"/>`) }],
    ["sparkle", { w: 9, svg: svg("100 100", `<path fill="${W}" d="M50 5c3 27 13 40 45 45-32 5-42 18-45 45-3-27-13-40-45-45 32-5 42-18 45-45z"/>`) }],
    ["moon", { w: 12, svg: svg("100 100", `<path fill="#f1e6c4" d="M62 9a42 42 0 1 0 30 64A37 37 0 0 1 62 9z"/>`) }],
    ["sun", { w: 14, svg: svg("100 100", `<circle cx="50" cy="50" r="17" ${line()}/>${petals(8, `<path ${line()} d="M50 9v13"/>`)}`) }],
    ["cloud", { w: 16, svg: svg("100 80", `<path ${line()} d="M27 66h47a16 16 0 0 0 2-32 22 22 0 0 0-42-6 19 19 0 0 0-7 38z"/>`) }],
    ["rain", { w: 16, svg: svg("100 100", `<path ${line()} d="M27 60h47a16 16 0 0 0 2-32 22 22 0 0 0-42-6 19 19 0 0 0-7 38z"/><path ${line()} d="M34 72l-5 14M52 72l-5 14M70 72l-5 14"/>`) }],
    ["flower", { w: 12, svg: svg("100 100", `<g fill="${W}">${petals(5, `<ellipse cx="50" cy="25" rx="12" ry="18"/>`)}</g><circle cx="50" cy="50" r="9" fill="#e8c96a"/>`) }],
    ["lily", { w: 18, svg: svg("120 90", `<ellipse cx="60" cy="66" rx="52" ry="17" fill="#8fa58c"/><path d="M60 66L98 52" stroke="#5d5d5d" stroke-width="2.5"/><g fill="${W}"><path d="M60 62C44 52 40 34 44 22c10 8 16 22 16 40z"/><path d="M60 62c16-10 20-28 16-40-10 8-16 22-16 40z"/><path d="M60 62c-6-14-6-32 0-46 6 14 6 32 0 46z"/><path d="M60 62C42 60 30 50 26 38c14 0 28 10 34 24z" opacity=".85"/><path d="M60 62c18-2 30-12 34-24-14 0-28 10-34 24z" opacity=".85"/></g><circle cx="60" cy="56" r="4" fill="#e8c96a"/>`) }],
    ["leaf", { w: 14, svg: svg("100 100", `<path ${line(2.5)} d="M18 88C36 62 56 40 84 14"/><g fill="#a9b8a0"><path d="M38 62c-14-2-22-12-24-24 14 0 24 8 24 24z"/><path d="M46 52c2-14 12-22 26-22-2 14-12 22-26 22z"/><path d="M56 40C52 26 58 14 70 8c4 14-2 26-14 32z"/><path d="M30 72c14 4 26 0 34-10-14-4-26 0-34 10z"/></g>`) }],
    ["fig", { w: 13, svg: svg("100 100", `<path fill="#6d5a7a" d="M50 8c7 12 32 27 32 52a32 32 0 0 1-64 0C18 35 43 20 50 8z"/><path fill="#f0e2d0" d="M50 24c5 9 24 20 24 37a24 24 0 0 1-48 0c0-17 19-28 24-37z"/><path fill="#c9655f" d="M50 38c4 6 15 13 15 24a15 15 0 0 1-30 0c0-11 11-18 15-24z"/><g fill="#f0e2d0"><circle cx="45" cy="58" r="1.6"/><circle cx="55" cy="56" r="1.6"/><circle cx="50" cy="66" r="1.6"/><circle cx="43" cy="68" r="1.6"/><circle cx="57" cy="67" r="1.6"/><circle cx="50" cy="50" r="1.6"/></g>`) }],
    ["crab", { w: 14, svg: svg("100 80", `<g fill="#d97757"><rect x="22" y="14" width="56" height="38"/><rect x="10" y="26" width="12" height="12"/><rect x="78" y="26" width="12" height="12"/><rect x="26" y="52" width="8" height="14"/><rect x="40" y="52" width="8" height="14"/><rect x="52" y="52" width="8" height="14"/><rect x="66" y="52" width="8" height="14"/></g><rect x="36" y="24" width="6" height="12" fill="#1f1f1f"/><rect x="58" y="24" width="6" height="12" fill="#1f1f1f"/>`) }],
    ["cat", { w: 14, svg: svg("100 100", `<path ${line()} d="M22 26l8 22c-6 7-9 15-9 22 0 13 13 21 29 21s29-8 29-21c0-7-3-15-9-22l8-22-19 12c-3-1-6-1-9-1s-6 0-9 1z"/><path ${line(2.5)} d="M37 62h.1M63 62h.1M46 72c2 2 6 2 8 0"/>`) }],
    ["cola", { w: 9, svg: svg("60 100", `<path fill="#232323" stroke="${W}" stroke-width="2" d="M14 12h32l4 8v64l-4 8H14l-4-8V20z"/><path stroke="${W}" stroke-width="2" d="M14 12h32"/><text x="30" y="56" text-anchor="middle" font-family="Helvetica,Arial,sans-serif" font-size="11" letter-spacing="1" fill="${W}">zero</text>`) }],
    ["coffee", { w: 13, svg: svg("100 100", `<path ${line()} d="M20 44h48v22a20 20 0 0 1-20 20h-8a20 20 0 0 1-20-20zM68 50h6a10 10 0 0 1 0 20h-7"/><path ${line(2.5)} d="M34 32c-4-6 4-8 0-14M48 32c-4-6 4-8 0-14"/>`) }],
    ["tooth", { w: 11, svg: svg("100 100", `<path fill="${W}" d="M30 16c9-7 14 1 20 1s11-8 20-1c11 9 6 26 2 38-3 10-4 32-11 32s-4-20-11-20-4 20-11 20-8-22-11-32c-4-12-9-29 2-38z"/>`) }],
    ["clip", { w: 7, svg: svg("60 100", `<path ${line(3.5)} d="M18 30v42a12 12 0 0 0 24 0V22a8 8 0 0 0-16 0v46a4 4 0 0 0 8 0V32"/>`) }],
    ["check", { w: 9, svg: svg("100 100", `<path ${line(6)} d="M14 54l22 22 50-54"/>`) }],
    ["arrow", { w: 16, svg: svg("100 80", `<path ${line()} d="M10 66c18-30 42-42 74-38M68 14l18 14-16 16"/>`) }],
    ["circle", { w: 26, svg: svg("160 100", `<path ${line(2.5)} d="M92 10C46 4 10 22 10 52s34 40 74 40 66-16 66-42S118 6 70 12"/>`) }],
    ["wave", { w: 28, svg: svg("200 30", `<path ${line(2.5)} d="M4 15c16-15 32 15 48 0s32 15 48 0 32 15 48 0 32 15 48 0"/>`) }],
    ["stamp", { w: 20, svg: svg("100 100", `<g fill="none" stroke="${W}" stroke-width="1.6" opacity=".9"><circle cx="50" cy="50" r="46"/><circle cx="50" cy="50" r="29"/></g><defs><path id="c" d="M50 50m-34 0a34 34 0 1 1 68 0a34 34 0 1 1-68 0"/></defs><text font-family="Helvetica,Arial,sans-serif" font-size="9.5" letter-spacing="2.4" fill="${W}"><textPath href="#c" startOffset="0">LITTLE MOMENTS · DAILY NOTES · TECHO ·</textPath></text><path fill="${W}" d="M50 62c-9-6-13-11-13-16 0-4 3-7 6-7s5 2 7 4c2-2 4-4 7-4s6 3 6 7c0 5-4 10-13 16z"/>`) }],
    ["ticket", { w: 36, svg: svg("220 90", `<path fill="#ece7dc" d="M6 4h208v26a15 15 0 0 0 0 30v26H6V60a15 15 0 0 0 0-30z"/><path stroke="#5d5d5d" stroke-width="1.5" stroke-dasharray="4 4" d="M160 8v74"/><g font-family="Helvetica,Arial,sans-serif" fill="#3a3a3a"><text x="28" y="38" font-size="19" font-weight="700" letter-spacing="2">TECHO LIVE</text><text x="28" y="58" font-size="10" letter-spacing="1.5">2027.03.20 · STUDIO</text><text x="28" y="73" font-size="8" letter-spacing="2" opacity=".7">STANDING · ADMIT ONE</text><text x="187" y="50" font-size="11" letter-spacing="2" text-anchor="middle" transform="rotate(90 187 46)">0320</text></g>`) }],
  ]);

  const EMOJI = ["🍣", "🥤", "☕", "🍊", "🧸", "🦀", "🐼", "🎬", "📖", "🌧", "✈️", "🦷", "🛍", "🍜", "🌙", "💤"];
  const cache = new Map();
  const src = (name) => {
    if (!cache.has(name)) cache.set(name, pack[name] ? `data:image/svg+xml,${encodeURIComponent(pack[name].svg)}` : null);
    return cache.get(name);
  };
  return { pack, EMOJI, src };
})();
