"use strict";
const app = document.getElementById("app");
const jid = location.pathname.split("/")[2];
const stateNames = {detecting:"正在切分镜",selection:"待选片",cleaning:"正在去字",quality:"待效果复审",
  assembling:"正在合成",done:"已出片",empty:"未保留片段",failed:"处理暂停"};
const modes = {"sttn-det":"自动识字 · STTN","sttn-auto":"框内整体修复 · STTN",lama:"自动识字 · LaMa",
  propainter:"自动识字 · ProPainter",opencv:"自动识字 · OpenCV"};
let timer, current, working = false;

function el(tag, text, cls) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (cls) node.className = cls;
  return node;
}
function btn(text, fn, cls) {
  const b=el("button",text,cls);
  b.type="button"; b.onclick=()=>Promise.resolve().then(fn).catch(alertError);
  return b;
}
function link(text,href,cls) {
  const a=el("a",text,cls); a.href=href; return a;
}
function alertError(error) {
  const m=document.getElementById("message"); m.textContent=String(error.message || error); m.hidden=false;
  window.setTimeout(()=>{m.hidden=true;},9000);
}
async function api(path, body) {
  const res=await fetch(path,body===undefined?{}:{method:"POST",headers:{"Content-Type":"application/json","X-Shotwork":"1"},
    body:JSON.stringify(body)});
  const data=await res.json(); if(!res.ok) throw Error(data.error || res.statusText); return data;
}
function field(label,node) {
  const l=el("label",label,"field"); l.append(node); return l;
}
function video(name) {
  const v=el("video"); v.controls=true; v.preload="metadata"; v.playsInline=true;
  v.src="/media/"+jid+"/"+name; return v;
}
function heading(text,small) {
  const box=el("div",undefined,"top"); const left=el("div");
  left.append(el("h1",text)); if(small) left.append(el("small",small)); box.append(left);return box;
}
async function home() {
  const [jobs,health]=await Promise.all([api("/api/jobs"),api("/api/health")]);
  app.replaceChildren(heading("视频任务"));
  const form=el("section"); const paths=el("textarea"); paths.rows=3; paths.placeholder="每行一个视频的完整路径";
  const output=el("input"); output.type="text";output.value=health.output;
  form.append(el("h2","新建任务"),field("本地视频",paths),field("成品目录",output));
  const go=btn("开始切分镜",async()=>{
    go.disabled=true;
    try {
      const sources=paths.value.split(/\r?\n/).map(p=>p.trim()).filter(Boolean);
      const created=await api("/api/jobs",{sources,output:output.value});
      if(created.length===1) location.assign("/review/"+created[0].id); else await home();
    } finally {go.disabled=false;}
  },"primary");
  form.append(go);app.append(form);
  if(jobs.length) {
    const box=el("section");box.append(el("h2","最近任务"));
    for(const j of jobs) {
      const row=el("div",undefined,"film");const label=el("div");
      label.append(el("strong",j.label),el("div",stateNames[j.state],"muted"));
      row.append(label,link("打开任务","/review/"+j.id,"button"));box.append(row);
    }
    app.append(box);
  }
}

function regionEditor(s, redo=false) {
  const details=el("details"),summary=el("summary");details.append(summary);
  const choice=structuredClone(s.areas);
  const mode=el("select");
  for(const [value,text] of Object.entries(modes)){const o=el("option",text);o.value=value;mode.append(o);}
  mode.value=redo ? (s.areas.length && s.mode!=="sttn-auto"?"sttn-auto":s.mode==="lama"?"sttn-det":"lama") : s.mode;
  const v=video(s.id+"-raw.mp4");const wrap=el("div",undefined,"video"),overlay=el("div",undefined,"overlay");
  wrap.append(v,overlay);const [w,h]=s.size;const text=el("small");
  function paint() {
    overlay.replaceChildren();
    for(const [y1,y2,x1,x2] of choice) {
      const r=el("div",undefined,"rect");
      Object.assign(r.style,{top:y1/h*100+"%",left:x1/w*100+"%",width:(x2-x1)/w*100+"%",height:(y2-y1)/h*100+"%"});
      overlay.append(r);
    }
    text.textContent=choice.length?"已框选 "+choice.length+" 个区域":"未框选时，识字模式会检查整个画面";
    summary.textContent=(redo?"返工设置":"去字范围")+" · "+(choice.length?"已框选 "+choice.length+" 处":"全画面识字");
  }
  let start;
  function pos(e) {
    const box=overlay.getBoundingClientRect();
    return [Math.round(Math.max(0,Math.min(1,(e.clientX-box.left)/box.width))*w),
      Math.round(Math.max(0,Math.min(1,(e.clientY-box.top)/box.height))*h)];
  }
  overlay.onpointerdown=e=>{start=pos(e);overlay.setPointerCapture(e.pointerId);choice.push([start[1],start[1],start[0],start[0]]);};
  overlay.onpointermove=e=>{if(!start)return;const [x,y]=pos(e);
    choice[choice.length-1]=[Math.min(start[1],y),Math.max(start[1],y),Math.min(start[0],x),Math.max(start[0],x)];paint();};
  overlay.onpointerup=e=>{if(!start)return;overlay.onpointermove(e); start=null;
    const r=choice.at(-1);if(r[1]-r[0]<2 || r[3]-r[2]<2)choice.pop();paint();};
  overlay.onpointercancel=()=>{if(start)choice.pop();start=null;paint();};
  const draw=btn("框选区域",()=>{v.pause();wrap.classList.toggle("drawing");
    draw.textContent=wrap.classList.contains("drawing")?"结束框选":"框选区域";});
  const tools=el("div",undefined,"tools");tools.append(draw,btn("撤销一框",()=>{choice.pop();paint();}),text);
  details.append(field("修复方式",mode),wrap,tools);
  paint();return {details,values:()=>({mode:mode.value,areas:choice})};
}
async function action(name,values={}) {
  if(working)return;working=true;
  try{current=await api("/api/jobs/"+jid,{version:current.version,action:name,...values});render(current);}
  catch(error){await load();throw error;}finally{working=false;}
}
function title(s) {return "分镜 "+s.id;}
function selection(j) {
  const cards=el("div",undefined,"grid"), bar=el("div",undefined,"bar");
  const info=el("strong");const entries=[];
  const ordered=()=>[...cards.children].map(node=>entries.find(e=>e.card===node));
  const update=()=>{info.textContent="已选 "+entries.filter(e=>e.cb.checked).length+" / "+entries.length+" 段";};
  for(const s of j.shots){
    const card=el("article");const cb=el("input");cb.type="checkbox";cb.checked=true;cb.onchange=update;
    const label=el("label");label.append(cb,document.createTextNode(" "+title(s)));
    const row=el("div",undefined,"row");row.append(label,el("small",(s.start_us/1e6).toFixed(2)+" – "+(s.end_us/1e6).toFixed(2)+" 秒"));
    const wrap=el("div",undefined,"video");wrap.append(video(s.id+"-raw.mp4"));
    const edit=regionEditor(s),order=el("div",undefined,"tools");
    order.append(btn("前移",()=>{if(card.previousElementSibling)cards.insertBefore(card,card.previousElementSibling);}),
      btn("后移",()=>{if(card.nextElementSibling)cards.insertBefore(card.nextElementSibling,card);}));
    card.append(row,wrap,edit.details,order);cards.append(card);entries.push({s,cb,card,edit});
  }
  bar.append(info,btn("确认选片，开始去字",()=>action("select",{shots:ordered().filter(e=>e.cb.checked).map(e=>({id:e.s.id,...e.edit.values()}))}),"primary"));
  update();app.append(cards,bar);
}
function quality(j) {
  const cards=el("div",undefined,"grid");let approved=0;const revisions=[];
  const marked=()=>revisions.filter(r=>r.cb.checked);
  const batch=btn("提交勾选返工",()=>action("redo_many",{shots:marked().map(r=>r.params())}));
  const merge=btn("按当前顺序合成",()=>action("finish"),"primary");
  const update=()=>{batch.disabled=marked().length===0;merge.disabled=approved!==j.selected.length || marked().length>0;};
  for(const sid of j.selected){
    const s=j.shots.find(item=>item.id===sid);const card=el("article");
    const h=el("div",undefined,"row");h.append(el("h3",title(s)+" · 修订 "+s.revision),el("span",s.approved?"已通过":"待审核","badge"));
    const raw=video(s.id+"-raw.mp4"),clean=video(s.id+"-r"+s.revision+".mp4");
    raw.muted=true;const pair=el("div",undefined,"pair");
    for(const [caption,v] of [["原片",raw],["处理版",clean]]){
      const half=el("div");half.append(el("small",caption),v);pair.append(half);
    }
    const sync=btn("同步播放",async()=>{raw.currentTime=clean.currentTime;await Promise.all([raw.play(),clean.play()]);});
    clean.onpause=()=>raw.pause();clean.onseeked=()=>{raw.currentTime=clean.currentTime;};
    const pass=btn("通过此版本",()=>action("approve",{id:s.id,revision:s.revision}),"primary");
    pass.disabled=Boolean(s.approved);if(s.approved)approved++;
    const edit=regionEditor(s,true),note=el("input");note.type="text";note.value=s.note;note.placeholder="例如第 1 秒漏字";
    const params=()=>({id:s.id,revision:s.revision,note:note.value,...edit.values()});
    const cb=el("input");cb.type="checkbox";cb.onchange=()=>{if(cb.checked)edit.details.open=true;update();};
    const flag=el("label");flag.append(cb,document.createTextNode(" 加入返工"));
    revisions.push({cb,params});
    const redo=btn("提交这段返工",()=>action("redo",params()));
    edit.details.append(field("返工备注",note),redo);
    const tools=el("div",undefined,"tools");tools.append(sync,pass);
    card.append(h,pair);if(s.result_note)card.append(el("p",s.result_note,"warn"));
    tools.append(flag);card.append(tools,edit.details);cards.append(card);
  }
  const bar=el("div",undefined,"bar");
  update();bar.append(el("strong","已通过 "+approved+" / "+j.selected.length+" 段"),batch,merge);
  app.append(cards,bar);
}
function render(j) {
  clearTimeout(timer);app.replaceChildren(heading(j.label,stateNames[j.state]+" · "+j.source));
  if(j.state==="selection")return selection(j);
  if(j.state==="quality")return quality(j);
  const box=el("section");app.append(box);
  if(j.state==="failed"){
    box.append(el("h2","处理暂停"),el("p",j.error,"warn"));
    const pending=j.selected.map(id=>j.shots.find(s=>s.id===id)).find(s=>!s.sha256);
    const edit=j.failed_stage==="cleaning" && pending?regionEditor(pending):null;
    if(edit)box.append(edit.details);
    const out=el("input");out.type="text";out.value=j.output;
    if(j.failed_stage==="assembling")box.append(field("成品目录",out));
    box.append(btn("重试当前步骤",()=>action("retry",edit?edit.values():{output:out.value}),"primary"));
  }else if(j.state==="done"){
    box.append(el("h2","完整成片"),video("master.mp4"));
    for(const p of j.files)box.append(el("p",p));
  }else if(j.state==="empty"){box.append(el("h2","本次没有保留分镜"));}
  else{
    box.append(el("h2",stateNames[j.state],"progress"));
    if(j.state==="cleaning")box.append(el("p","已处理 "+j.shots.filter(s=>s.sha256).length+" / "+j.selected.length+" 段"));
    timer=setTimeout(()=>load().catch(alertError),1700);
  }
}
async function load(){current=await api("/api/jobs/"+jid);render(current);}
(jid?load():home()).catch(alertError);
