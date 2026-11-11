"use strict";
// Fictional, read-only browser data. No real API, login, database or credentials.
window.TECHO_DEMO = true;
(() => {
  const original = window.fetch.bind(window);
  const apiBase = new URL("api/v1/", location.href);
  const pad = (n) => String(n).padStart(2, "0");
  const now = new Date();
  const currentMonth = `${now.getFullYear()}-${pad(now.getMonth() + 1)}`;
  const currentDay = `${currentMonth}-${pad(now.getDate())}`;
  const demoItems = [
    {item_type:"sticker", ref:"pack:tape-sage", text:null, color:null, x:0.5, y:0.06, scale:1, rotation:-4, z:0},
    {item_type:"photo", ref:"901", text:"示例照片", color:null, x:0.34, y:0.34, scale:1, rotation:3, z:1},
    {item_type:"sticker", ref:"pack:lily", text:null, color:null, x:0.76, y:0.56, scale:1, rotation:6, z:2},
    {item_type:"sticker", ref:"pack:sparkle", text:null, color:null, x:0.82, y:0.2, scale:1, rotation:0, z:3},
    {item_type:"text", ref:"hand", text:"一个安静的下午", color:"#f4f2ee", x:0.55, y:0.8, scale:1, rotation:0, z:4}
  ];
  function week(date) {
    const t = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
    t.setUTCDate(t.getUTCDate() + 4 - (t.getUTCDay() || 7));
    return `${t.getUTCFullYear()}-W${pad(Math.ceil(((t - Date.UTC(t.getUTCFullYear(), 0, 1)) / 864e5 + 1) / 7))}`;
  }
  function sample(ym) {
    const [y, m] = ym.split("-").map(Number);
    const isCurrent = ym === currentMonth;
    const day = `${ym}-${pad(isCurrent ? now.getDate() : 8)}`;
    const common = {created_at:`${day}T09:00:00+08:00`, updated_at:`${day}T09:00:00+08:00`, deleted_at:null};
    const photo = {...common, id:901, date:day, author:"human", updated_by:"human", caption:"示例照片", width:800, height:800, hash:"demo-photo"};
    const peekItems = demoItems.filter((x) => x.item_type !== "text").map(({item_type,ref,x,y,scale,rotation,z}) => ({item_type,ref,x,y,scale,rotation,z}));
    const weeks = {};
    const first = new Date(y, m - 1, 1), start = new Date(first);
    start.setDate(1 - (first.getDay() + 6) % 7);
    for (let d = new Date(start); d < new Date(y, m, 1); d.setDate(d.getDate() + 7)) weeks[week(d)] = [];
    weeks[week(new Date(`${day}T12:00:00`))] = [{...common,id:11,author:"human",updated_by:"human",scope:"week",period:week(new Date(`${day}T12:00:00`)),text:"整理一页阅读笔记（示例）",status:"open",sort:0}];
    return {ym,notes:[
      {...common,id:1,date:day,author:"human",updated_by:"human",text:"今天尝试了一种新的排版，留白让内容更清楚。",mood:"☀"},
      {...common,id:2,date:day,author:"agent",updated_by:"agent",text:"示例补记：可以把喜欢的配色加入下周灵感清单。",mood:null}
    ],media:[{...common,id:3,date:day,author:"human",updated_by:"human",kind:"book",title:"设计入门 · 虚构示例",note:"阅读摘记"}],
      events:[{...common,id:4,date:day,author:"human",updated_by:"human",kind:"plan",title:"参观示例展览",time:"14:00",place:"示例展厅"}],
      goals:{month:[{...common,id:12,author:"human",updated_by:"human",scope:"month",period:ym,text:"完成一个创意练习（示例）",status:"open",sort:0}],weeks},photos:isCurrent ? [photo] : [],decorated_pages:isCurrent ? [`day:${day}`] : [],page_peeks:isCurrent ? {[`day:${day}`]: peekItems} : {}};
  }
  window.fetch = async (input, init = {}) => {
    const url = new URL(typeof input === "string" || input instanceof URL ? input : input.url, location.href);
    if (url.origin !== apiBase.origin || !url.pathname.startsWith(apiBase.pathname)) return original(input, init);
    const method = (init.method || input?.method || "GET").toUpperCase();
    const reply = (data, status=200) => new Response(JSON.stringify(data), {status, headers:{"content-type":"application/json"}});
    if (method !== "GET") return reply({error:{message:"示例模式仅供浏览，不会保存输入。"}},403);
    const endpoint = url.pathname.slice(apiBase.pathname.length);
    if (endpoint === "me") return reply({author:"human"});
    if (endpoint === "month") return reply(sample(url.searchParams.get("ym") || currentMonth));
    if (endpoint === "decorations") {
      const page = url.searchParams.get("page");
      if (page === `day:${currentDay}`) {
        return reply({page, version:"2026-11-11T09:10:00.000000+08:00", items:demoItems});
      }
      return reply({page, version:null, items:[]});
    }
    if (endpoint === "strokes") return reply({page:url.searchParams.get("page"),strokes:[]});
    if (endpoint.startsWith("photos/")) return original(new URL("demo-photo.svg", location.href), init);
    if (endpoint === "changes") return reply({changes:[],cursor:new Date().toISOString(),has_more:false});
    return reply({error:{message:"演示未提供此资源。"}},404);
  };
})();
