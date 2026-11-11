"use strict";
const {test} = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const code = fs.readFileSync(path.join(__dirname,"../frontend/demo-data.js"),"utf8");

function demo() {
  const requests=[];
  const window={fetch:async(...args)=>{requests.push(args);throw new Error("network was reached");}};
  vm.runInNewContext(code,{window,location:new URL("https://portfolio.example.com/frontend/demo.html"),URL,Response,Date});
  return {window,requests};
}

test("demo serves fictional calendar data without reaching a backend",async()=>{
  const {window,requests}=demo();
  assert.equal(window.TECHO_DEMO,true);
  for(const ym of ["2026-01","2026-12","2027-01"]){
    const response=await window.fetch(`api/v1/month?ym=${ym}`);
    assert.equal(response.status,200);
    const data=await response.json();
    assert.equal(data.ym,ym);
    assert.ok(data.notes.every(x=>x.date.startsWith(ym)));
    assert.deepEqual([...new Set(data.notes.map(x=>x.author))].sort(),["agent","human"]);
    assert.ok(Object.keys(data.goals.weeks).length>=4);
  }
  assert.equal((await (await window.fetch("api/v1/me")).json()).author,"human");
  assert.equal(requests.length,0);
});

test("every demo write is refused locally, including Request objects",async()=>{
  const {window,requests}=demo();
  for(const method of ["POST","PUT","PATCH","DELETE"]){
    const response=await window.fetch("api/v1/notes",{method,body:"{}"});
    assert.equal(response.status,403);
  }
  assert.equal((await window.fetch(new Request("https://portfolio.example.com/frontend/api/v1/photos",{method:"POST"}))).status,403);
  assert.equal((await window.fetch("api/v1/not-implemented")).status,404);
  assert.equal(requests.length,0);
});
