
(()=>{'use strict';
// Never run inside somebody else's page (GitHub Pages cannot send X-Frame-Options, so the page guards itself).
if(window.top!==window.self){document.documentElement.style.display='none';return}
const CFG=window.OJALOOM_CONFIG||{};
// The web app and the server are separate sites. Every server path goes through U() to become an address on the API host.
const API=String(CFG.apiBase||'').replace(/\/+$/,'');
const U=p=>/^\//.test(p)?API+p:p;
const appBase=()=>location.origin+location.pathname.replace(/[^/]*$/,'');
const SUPPORT_WA=String(CFG.supportWhatsapp||'').replace(/\D/g,'');
// Filled from GET /api/boot before anything is drawn; these are only the values to fall back on.
const BOOT={categories:[],minPassword:10,version:'',referral:{referred:7,referrer:14,max:5},share:{whatsapp_direct:false}};
const $=(s,r=document)=>r.querySelector(s);
const $$=(s,r=document)=>[...r.querySelectorAll(s)];
const esc=s=>String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
const money=(n,compact)=>{n=Number(n||0);const neg=n<0;n=Math.abs(n);const whole=!!compact&&Number.isInteger(n);return (neg?'-':'')+'\u20a6'+n.toLocaleString('en-NG',{minimumFractionDigits:whole?0:2,maximumFractionDigits:whole?0:2})};
const pd=s=>{if(!s)return null;const m=/^(\d{4})-(\d{2})-(\d{2})$/.exec(s);return m?new Date(+m[1],+m[2]-1,+m[3]):new Date(s)};
const fmtDate=s=>{const d=pd(s);return d&&!isNaN(d)?d.toLocaleDateString('en-NG',{day:'numeric',month:'short',year:'numeric'}):'\u2014'};
const todayLocal=()=>new Date().toLocaleDateString('en-CA');
const ACT={},FORMS={},LIVE={},CALC={},LOAD={};

/* ---------- icons ---------- */
const IC={
dashboard:'<rect x="3" y="3" width="7" height="9" rx="1.6"/><rect x="14" y="3" width="7" height="5" rx="1.6"/><rect x="14" y="12" width="7" height="9" rx="1.6"/><rect x="3" y="16" width="7" height="5" rx="1.6"/>',
orders:'<path d="M8 6h12M8 12h12M8 18h12"/><circle cx="4" cy="6" r=".8"/><circle cx="4" cy="12" r=".8"/><circle cx="4" cy="18" r=".8"/>',
products:'<path d="M12 3l8.5 4.5v9L12 21l-8.5-4.5v-9L12 3z"/><path d="M3.8 7.7L12 12l8.2-4.3M12 12v9"/>',
customers:'<circle cx="9" cy="8" r="3.4"/><path d="M2.8 20c.6-3.4 3-5.2 6.2-5.2s5.6 1.8 6.2 5.2"/><path d="M16.2 4.9a3.4 3.4 0 010 6.4M18.6 14.9c1.7.6 2.7 2.1 3.1 4.6"/>',
debts:'<path d="M4 7.5A2.5 2.5 0 016.5 5H18a1 1 0 011 1v2.5"/><path d="M4 7.5V18a2 2 0 002 2h12a1 1 0 001-1v-3"/><path d="M20.5 9.5h-4a2.5 2.5 0 000 5h4v-5z"/>',
receipts:'<path d="M6 3h12v18l-3-2-3 2-3-2-3 2V3z"/><path d="M9.5 8h5M9.5 12h5"/>',
storefront:'<path d="M3.5 9.5L5 4h14l1.5 5.5"/><path d="M3.5 9.5a2.8 2.8 0 005.5 0 2.8 2.8 0 006 0 2.8 2.8 0 005.5 0"/><path d="M5 12.5V20h14v-7.5"/><path d="M10 20v-4.5h4V20"/>',
reports:'<path d="M3 3v18h18"/><path d="M7.5 15.5l3.5-4 3 2.5 5-6"/>',
settings:'<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2.2"/><circle cx="9" cy="17" r="2.2"/>',
plus:'<path d="M12 5v14M5 12h14"/>',
search:'<circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4-4"/>',
x:'<path d="M6 6l12 12M18 6L6 18"/>',
chev:'<path d="M6 9l6 6 6-6"/>',
check:'<path d="M5 12.5l4.5 4.5L19 7.5"/>',
sun:'<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4"/>',
moon:'<path d="M20 14.5A8.5 8.5 0 119.5 4a7 7 0 0010.5 10.5z"/>',
logout:'<path d="M9 4H6a2 2 0 00-2 2v12a2 2 0 002 2h3"/><path d="M16 8l4 4-4 4M20 12H9"/>',
trash:'<path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 002 2h6a2 2 0 002-2l1-12M9 7V4h6v3"/>',
image:'<rect x="3.5" y="4.5" width="17" height="15" rx="2.5"/><circle cx="9" cy="10" r="1.6"/><path d="M4 17l5-4.5 4 3.5 3-2.5 4.5 3.5"/>',
eye:'<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="2.8"/>',
eyeoff:'<path d="M3 3l18 18M10.6 5.7A9 9 0 0112 5.5c6 0 9.5 6.5 9.5 6.5a16 16 0 01-3 3.8M6.5 7.4A15.7 15.7 0 002.5 12S6 18.5 12 18.5a9 9 0 003.4-.7"/><path d="M9.9 9.9a2.8 2.8 0 003.9 3.9"/>',
copy:'<rect x="8.5" y="8.5" width="12" height="12" rx="2.5"/><path d="M15.5 8.5v-2a2 2 0 00-2-2h-7a2 2 0 00-2 2v7a2 2 0 002 2h2"/>',
ext:'<path d="M14 4h6v6M20 4l-9 9M18 14v4a2 2 0 01-2 2H6a2 2 0 01-2-2V8a2 2 0 012-2h4"/>',
alert:'<path d="M12 4l9 16H3L12 4z"/><path d="M12 10v4M12 17.5v.01"/>',
shield:'<path d="M12 3l7.5 3v5.5c0 4.5-3.2 8-7.5 9.5-4.3-1.5-7.5-5-7.5-9.5V6L12 3z"/><path d="M9 12l2.2 2.2L15.5 10"/>',
tag:'<path d="M3.5 12.2V4.5a1 1 0 011-1h7.7a1 1 0 01.7.3l7.3 7.3a1 1 0 010 1.4l-7.7 7.7a1 1 0 01-1.4 0L3.8 13a1 1 0 01-.3-.8z"/><circle cx="8" cy="8" r="1.3"/>',
more:'<circle cx="5.5" cy="12" r="1.4"/><circle cx="12" cy="12" r="1.4"/><circle cx="18.5" cy="12" r="1.4"/>',
edit:'<path d="M4 20h4L19 9l-4-4L4 16v4z"/><path d="M13.5 6.5l4 4"/>',
chat:'<path d="M20 11.5a8 8 0 01-11.8 7L4 20l1.5-4.1A8 8 0 1120 11.5z"/>',
stock:'<path d="M4 8l8-4 8 4v8l-8 4-8-4V8z"/><path d="M4 8l8 4 8-4M12 12v8"/>',
download:'<path d="M12 4v11M7.5 10.5L12 15l4.5-4.5M5 19.5h14"/>',
gift:'<rect x="3.5" y="9" width="17" height="11" rx="2"/><path d="M12 9v11M3.5 13.5h17"/><path d="M12 9c-2.6 0-4.6-.9-4.6-2.7C7.4 4.9 8.5 4 9.7 4 11.2 4 12 6.3 12 9zM12 9c2.6 0 4.6-.9 4.6-2.7 0-1.4-1.1-2.3-2.3-2.3C12.8 4 12 6.3 12 9z"/>'
};
IC.referrals=IC.gift;
IC.expenses='<path d="M4 7.5A2.5 2.5 0 016.5 5H18v3"/><path d="M4 7.5V17a2 2 0 002 2h13a1 1 0 001-1V9a1 1 0 00-1-1H6.5A2.5 2.5 0 014 7.5z"/><circle cx="16" cy="13.5" r="1.2"/>';
IC.history='<path d="M3.5 12a8.5 8.5 0 108.5-8.5A8.6 8.6 0 005.7 6.4L3.5 9"/><path d="M3.5 4v5h5"/><path d="M12 7.5V12l3 2"/>';
IC.billing='<rect x="3" y="5.5" width="18" height="13" rx="2.5"/><path d="M3 10h18M7 15h4"/>';
IC.lock='<rect x="5" y="10.5" width="14" height="9.5" rx="2.5"/><path d="M8 10.5V8a4 4 0 018 0v2.5"/>';
IC.mail='<rect x="3.5" y="5.5" width="17" height="13" rx="2.5"/><path d="M4 7.5l8 6 8-6"/>';
IC.pdf='<path d="M7 3h7l5 5v11a2 2 0 01-2 2H7a2 2 0 01-2-2V5a2 2 0 012-2z"/><path d="M14 3v5h5M8.5 14h7M8.5 17.5h5"/>';
const ico=(n,c='')=>`<svg class="ico ${c}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${IC[n]||''}</svg>`;
const MARK='<svg class="mark" viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="9" fill="#f2b01e"/><circle cx="16" cy="16" r="6.8" fill="none" stroke="#151c4a" stroke-width="4.6"/></svg>';

/* ---------- state ---------- */
const S={busy:0,busyT:null,pendingGo:null,shownHash:null,back:false,skipPush:false,me:null,biz:null,csrf:null,route:{view:'dashboard',id:'',q:{}},cats:null,nav:0,map:{},pf:{q:'',cat:'',stock:'',catCfg:null},of:{q:'',status:''},cf:{q:''},orderProds:new Map(),lineHtml:null};
const VIEWS=['dashboard','orders','customers','debts','receipts','products','storefront','reports','expenses','history','billing','referrals','settings'];
const LABEL={dashboard:'Dashboard',orders:'Orders',customers:'Customers',debts:'Debts',receipts:'Receipts',products:'Products',storefront:'Storefront',reports:'Reports',expenses:'Expenses',history:'Edit history',billing:'Oja Loom Pro',referrals:'Referrals',settings:'Settings'};
const NAV=[['',['dashboard']],['Sales',['orders','customers','debts','receipts']],['Catalogue',['products','storefront']],['Insights',['reports','expenses','history']],['Account',['billing','referrals','settings']]];

/* ---------- navigation history ---------- */
let hIndex=0;
(()=>{const st=history.state;hIndex=st&&typeof st.i==='number'?st.i:0;try{history.replaceState({i:hIndex},'',location.href)}catch(e){}})();

/* ---------- referral link capture ---------- */
const cleanRef=v=>String(v||'').replace(/[^A-Za-z0-9]/g,'').toUpperCase().slice(0,12);
(()=>{let r='';try{r=cleanRef(new URLSearchParams(location.search).get('ref'))}catch(e){}
  if(r){try{sessionStorage.setItem('ojaloom-ref',r)}catch(e){}try{history.replaceState(null,'',location.pathname+location.hash)}catch(e){}}
  else{try{r=cleanRef(sessionStorage.getItem('ojaloom-ref'))}catch(e){}}
  S.ref=r;S.refInfo=null})();
function clearRef(){S.ref='';S.refInfo=null;try{sessionStorage.removeItem('ojaloom-ref')}catch(e){}}

/* ---------- theme ---------- */
const THEME_KEY='ojaloom-theme';
function getTheme(){let t=null;try{t=localStorage.getItem(THEME_KEY)}catch(e){}return t||(matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light')}
function setTheme(t,save){document.documentElement.dataset.theme=t;const m=$('meta[name=theme-color]');if(m)m.content=t==='dark'?'#080b22':'#151c4a';if(save){try{localStorage.setItem(THEME_KEY,t)}catch(e){}}}
setTheme(getTheme());

/* ---------- api ---------- */
async function api(path,opt={}){
  const method=(opt.method||'GET').toUpperCase();
  if(method!=='GET')PDFC.clear();
  const headers={'Accept':'application/json'};
  let body;
  if(opt.body!==undefined){headers['Content-Type']='application/json';body=JSON.stringify(opt.body)}
  if(method!=='GET'&&S.csrf)headers['X-CSRF-Token']=S.csrf;
  let res;
  try{res=await fetch(U(path),{method,headers,body,credentials:'include'})}catch(e){throw new Error('Cannot reach the Oja Loom server. Check your connection and try again.')}
  let data={};try{data=await res.json()}catch(e){}
  if(!res.ok){
    if(res.status===401&&S.me&&!/^\/api\/(login|signup|logout)/.test(path)){S.me=null;S.biz=null;S.csrf=null;closeLayers();render();toast('Your session ended. Please log in again.',true)}
    const err=new Error(data.error||'Something went wrong. Please try again.');err.status=res.status;
    if(res.status===402&&data.upgrade){err.upgrade=data.upgrade;S.paywallMsg=err.message;showUpgrade(data.upgrade,err.message)}
    throw err}
  return data}

/* ---------- small UI helpers ---------- */
function toast(msg,bad=false){if(bad&&S.paywallMsg&&msg===S.paywallMsg){S.paywallMsg='';return}const box=$('#toasts');const t=document.createElement('div');t.className='toast'+(bad?' bad':'');t.innerHTML=ico(bad?'alert':'check')+'<span></span>';t.lastChild.textContent=msg;box.appendChild(t);setTimeout(()=>{t.classList.add('out');setTimeout(()=>t.remove(),260)},bad?5200:2800)}
function busy(btn,on,text){if(!btn)return;btn.disabled=on;if(text!==undefined)btn.textContent=text}
const alertBox=(m,cls='')=>`<div class="alert ${cls}" role="alert">${ico('alert')}<span>${esc(m)}</span></div>`;
function formErr(f,msg){if(S.paywallMsg&&msg===S.paywallMsg){S.paywallMsg='';return}const box=$('.ferr',f);if(box){box.innerHTML=alertBox(msg);box.scrollIntoView({block:'nearest',behavior:'smooth'})}else toast(msg,true)}
const skel=(n=4)=>`<div class="panel"><div class="panel-b">${Array.from({length:n},()=>'<div class="sk" style="height:46px;margin-bottom:10px"></div>').join('')}</div></div>`;
const emptyBox=(icon,title,text,btn='')=>`<div class="empty"><div class="bub">${ico(icon)}</div><strong>${esc(title)}</strong><div>${esc(text)}</div>${btn}</div>`;
const pageHead=(title,sub='',actions='')=>`<div class="phead"><div><h1>${esc(title)}</h1>${sub?`<p>${esc(sub)}</p>`:''}</div><div class="phead-a">${actions}</div></div>`;
const SECONDARY=['debts','receipts','storefront','reports','expenses','history','billing','referrals','settings'];
function backHtml(){
  const r=S.route;if(!r||r.view==='dashboard')return '';
  const btn=(to,cls)=>`<button type="button" class="back${cls||''}" data-act="back" data-to="${to}">${ico('chev')}Back</button>`;
  if(r.view==='orders'&&r.id)return btn('orders');
  if(SECONDARY.includes(r.view))return btn('dashboard');
  return hIndex>0?btn('dashboard',' mob'):''}
const setPage=h=>{const p=$('#page');if(p)p.innerHTML=backHtml()+h};
const ST={pending:['','Pending'],confirmed:['','Confirmed'],processing:['gold','Processing'],ready:['warn','Ready'],completed:['ok','Completed'],cancelled:['bad','Cancelled'],paid:['ok','Paid'],partially_paid:['warn','Part paid'],overdue:['bad','Overdue'],outstanding:['gold','Outstanding'],in:['ok','In stock'],low:['warn','Low stock'],out:['bad','Out of stock']};
const pill=k=>{const s=ST[k]||['',k];return `<span class="pill ${s[0]}">${esc(s[1])}</span>`};
const initial=s=>esc((String(s||'?').trim()[0]||'?').toUpperCase());

/* ---------- layers (drawers and dialogs) ---------- */
const layers=[];
const lockScroll=()=>document.body.classList.toggle('lock',layers.length>0);
function openLayer(html,{center=false,label=''}={}){
  const w=document.createElement('div');w.className='wrap'+(center?' center':'');w.setAttribute('role','dialog');w.setAttribute('aria-modal','true');if(label)w.setAttribute('aria-label',label);
  w.innerHTML=html;w._prev=document.activeElement;
  $('#layers').appendChild(w);layers.push(w);lockScroll();
  if(S.skipPush)S.skipPush=false;else{try{history.pushState({i:hIndex,L:layers.length},'',location.href)}catch(e){}}
  const inner=w.firstElementChild;if(inner)inner.setAttribute('tabindex','-1');
  const first=$('.d-body input:not([type=hidden]):not(.sr),.d-body textarea,.dlg input:not([type=hidden]):not(.sr),.dlg textarea',w);
  if(first&&matchMedia('(hover:hover)').matches)first.focus();else if(inner)inner.focus({preventScroll:true});
  return w}
function closeTop(){ddClose();const w=layers.pop();if(!w)return;if(w._confirm){const c=w._confirm;w._confirm=null;c(false)}w.remove();lockScroll();const p=w._prev;if(p&&document.contains(p)&&p.focus)p.focus({preventScroll:true})}
function histBack(n){if(n<1)return;S.busy++;clearTimeout(S.busyT);S.busyT=setTimeout(()=>{if(S.busy>0){S.busy=0;flushNav()}},800);history.go(-n)}
function closeLayer(){if(!layers.length)return;closeTop();histBack(1)}
function closeLayers(){const n=layers.length;if(!n)return;while(layers.length)closeTop();histBack(n)}
function drawer({title,body,foot='',wide=false}){return openLayer(`<div class="drawer${wide?' wide':''}"><div class="d-head"><h2>${esc(title)}</h2><button type="button" class="btn ghost icon" data-act="close-layer" aria-label="Close">${ico('x')}</button></div><div class="d-body">${body}</div>${foot?`<div class="d-foot">${foot}</div>`:''}</div>`,{label:title})}
function dialog(html,label){return openLayer(`<div class="dlg">${html}</div>`,{center:true,label})}
function confirmBox({title,text,ok='Confirm',danger=false}){return new Promise(res=>{const w=dialog(`<h2>${esc(title)}</h2><p class="muted">${esc(text)}</p><div class="dlg-act"><button type="button" class="btn" data-act="confirm-no">Cancel</button><button type="button" class="btn ${danger?'danger solid':'primary'}" data-act="confirm-yes">${esc(ok)}</button></div>`,title);w._confirm=res})}
function trapTab(e){const w=layers[layers.length-1];if(!w||ddOpenState)return;const f=$$('a[href],button:not([disabled]),input:not([disabled]):not([type=hidden]),textarea:not([disabled]),[tabindex="0"]',w).filter(x=>x.offsetParent!==null);if(!f.length)return;const a=f[0],z=f[f.length-1];if(e.shiftKey&&(document.activeElement===a||document.activeElement===w.firstElementChild)){e.preventDefault();z.focus()}else if(!e.shiftKey&&document.activeElement===z){e.preventDefault();a.focus()}}

/* ---------- dropdown ---------- */
const DD=new Map();let ddSeq=0;let ddOpenState=null;
const ddText=(cfg,val)=>{if(val===''&&cfg.emptyPh)return{t:cfg.placeholder||'Select\u2026',ph:true};const o=(cfg.options||[]).find(o=>o.v===val);if(o)return{t:o.l,ph:false};if(val)return{t:val,ph:false};return{t:cfg.placeholder||'Select\u2026',ph:true}};
function dd(cfg){
  const id='dd'+(++ddSeq);cfg.id=id;DD.set(id,cfg);if(DD.size>600)DD.delete(DD.keys().next().value);
  const val=cfg.value??'';const x=ddText(cfg,val);
  return `<div class="dd${cfg.sm?' sm':''}" data-dd="${id}"><input type="hidden" ${cfg.name?`name="${esc(cfg.name)}" `:''}value="${esc(val)}"><button type="button" class="dd-btn${x.ph?' ph':''}" data-act="dd-open" data-id="${id}" aria-haspopup="listbox" aria-expanded="false"${cfg.label?` aria-label="${esc(cfg.label)}"`:''}><span class="dd-val">${esc(x.t)}</span>${ico('chev')}</button></div>`}
function ddSet(id,v,quiet){
  const cfg=DD.get(id);const root=$(`[data-dd="${id}"]`);if(!cfg||!root)return;
  const inp=$('input[type=hidden]',root);inp.value=v;const x=ddText(cfg,v);$('.dd-val',root).textContent=x.t;$('.dd-btn',root).classList.toggle('ph',x.ph);
  if(!quiet){inp.dispatchEvent(new Event('input',{bubbles:true}));if(cfg.onChange)cfg.onChange(v)}}
function ddItems(st){
  const q=st.q.trim().toLowerCase();const cfg=st.cfg;
  const items=(cfg.options||[]).filter(o=>!q||String(o.l).toLowerCase().includes(q)||String(o.h||'').toLowerCase().includes(q)).map(o=>({t:'o',o}));
  if(cfg.create&&q&&!(cfg.options||[]).some(o=>String(o.l).toLowerCase()===q))items.push({t:'n',name:st.q.trim()});
  return items}
function ddRender(){
  const st=ddOpenState;if(!st)return;const cfg=st.cfg;
  st.items=ddItems(st);if(st.hl>=st.items.length)st.hl=Math.max(0,st.items.length-1);
  let h='',last=null;
  st.items.forEach((it,i)=>{
    const hl=i===st.hl?' hl':'';
    if(it.t==='o'){const o=it.o;if(o.g&&o.g!==last)h+=`<li class="dd-grp" role="presentation">${esc(o.g)}</li>`;last=o.g||null;const sel=o.v===st.cur;
      h+=`<li class="dd-opt${hl}" role="option" id="${st.id}-o${i}" data-i="${i}" aria-selected="${sel}"><span class="l">${esc(o.l)}</span>${o.h?`<span class="h">${esc(o.h)}</span>`:''}${sel?ico('check'):''}</li>`}
    else h+=`<li class="dd-opt dd-new${hl}" role="option" id="${st.id}-o${i}" data-i="${i}"><span class="l">${ico('plus')}<span>Add \u201c${esc(it.name)}\u201d as a new ${esc(cfg.create.noun||'option')}</span></span></li>`});
  if(!st.items.length)h+=`<li class="dd-empty">No matches${cfg.create?'. Type a name to add it.':'.'}</li>`;
  else if(cfg.create&&!st.q.trim())h+=`<li class="dd-grp" role="presentation">Not listed? Type its name to add it.</li>`;
  const list=$('#ddlayer .dd-list');if(!list)return;list.innerHTML=h;
  const q=$('#ddlayer .dd-q');if(q)q.setAttribute('aria-activedescendant',`${st.id}-o${st.hl}`);
  const cur=$('.hl',list);if(cur)cur.scrollIntoView({block:'nearest'})}
function placeMenu(m,anchor,minW=220){
  const r=anchor.getBoundingClientRect();const w=Math.min(Math.max(r.width,minW),innerWidth-24);
  m.style.width=w+'px';m.style.left=Math.max(12,Math.min(r.left,innerWidth-w-12))+'px';
  const below=innerHeight-r.bottom-14,above=r.top-14;
  if(below<300&&above>below){m.style.bottom=(innerHeight-r.top+6)+'px';m.style.maxHeight=Math.min(420,above-6)+'px'}
  else{m.style.top=(r.bottom+6)+'px';m.style.maxHeight=Math.min(420,below-6)+'px'}}
function ddOpen(id){
  const cfg=DD.get(id);const root=$(`[data-dd="${id}"]`);if(!cfg||!root)return;
  if(ddOpenState&&ddOpenState.id===id){ddClose(true);return}
  ddClose();
  const btn=$('.dd-btn',root);btn.setAttribute('aria-expanded','true');
  const cur=$('input[type=hidden]',root).value;
  const searchable=cfg.search??((cfg.options||[]).length>7||!!cfg.create);
  const st={kind:'select',id,cfg,btn,cur,q:'',hl:0,items:[],searchable};ddOpenState=st;
  st.items=ddItems(st);st.hl=Math.max(0,st.items.findIndex(it=>it.t==='o'&&it.o.v===cur));
  const layer=$('#ddlayer');
  layer.innerHTML=`<div class="dd-back" data-act="dd-close"></div><div class="dd-menu">${searchable?`<div class="dd-search"><input type="text" class="dd-q" role="combobox" aria-expanded="true" aria-controls="${id}-list" placeholder="${esc(cfg.searchPlaceholder||'Search\u2026')}" autocomplete="off" spellcheck="false" aria-label="Search options"></div>`:''}<ul class="dd-list" id="${id}-list" role="listbox" tabindex="0" aria-label="${esc(cfg.label||'Options')}"></ul></div>`;
  placeMenu($('.dd-menu',layer),btn);ddRender();
  const q=$('.dd-q',layer);
  if(q){if(matchMedia('(hover:hover)').matches)q.focus({preventScroll:true});else $('.dd-list',layer).focus({preventScroll:true})}else $('.dd-list',layer).focus({preventScroll:true})}
function popMenu(anchor,items,label){
  ddClose();anchor.setAttribute('aria-expanded','true');ddOpenState={kind:'menu',btn:anchor};
  const layer=$('#ddlayer');
  layer.innerHTML=`<div class="dd-back" data-act="dd-close"></div><div class="dd-menu" role="menu" aria-label="${esc(label||'Create new')}"><div class="dd-list">${items.map(i=>`<button type="button" class="dd-opt" role="menuitem" data-act="menu-run" data-run="${esc(i.run)}"${i.attrs||''}>${ico(i.icon)}<span class="l">${esc(i.label)}</span></button>`).join('')}</div></div>`;
  placeMenu($('.dd-menu',layer),anchor,210);const m=$('.dd-menu',layer);m.style.left='';m.style.right=Math.max(12,innerWidth-anchor.getBoundingClientRect().right)+'px';
  const f=$('.dd-opt',layer);if(f)f.focus()}
function ddClose(refocus){
  const st=ddOpenState;if(!st)return;ddOpenState=null;
  const l=$('#ddlayer');if(l)l.innerHTML='';
  if(st.btn){st.btn.setAttribute('aria-expanded','false');if(refocus&&document.contains(st.btn))st.btn.focus({preventScroll:true})}}
function ddCommit(st,v){ddSet(st.id,v);ddClose(true)}
async function ddPick(i){
  const st=ddOpenState;if(!st||st.kind!=='select')return;const it=st.items[i];if(!it)return;
  if(it.t==='o'){ddCommit(st,it.o.v);return}
  try{const name=await st.cfg.create.fn(it.name);if(st.cfg.rebuild)st.cfg.options=st.cfg.rebuild();ddCommit(st,name)}catch(e){toast(e.message,true)}}
function ddKey(e){
  const st=ddOpenState;if(!st)return false;
  if(e.key==='Escape'){e.preventDefault();e.stopPropagation();ddClose(true);return true}
  if(st.kind!=='select'){if(e.key==='Tab')ddClose();return false}
  const n=st.items.length;
  if(e.key==='ArrowDown'){e.preventDefault();if(n){st.hl=(st.hl+1)%n;ddRender()}return true}
  if(e.key==='ArrowUp'){e.preventDefault();if(n){st.hl=(st.hl-1+n)%n;ddRender()}return true}
  if(e.key==='Home'){e.preventDefault();st.hl=0;ddRender();return true}
  if(e.key==='End'){e.preventDefault();st.hl=Math.max(0,n-1);ddRender();return true}
  if(e.key==='Enter'){e.preventDefault();ddPick(st.hl);return true}
  if(e.key==='Tab'){ddClose();return false}
  return false}

/* ---------- categories ---------- */
async function loadCats(force){if(S.cats&&!force)return S.cats;const d=await api('/api/categories');S.cats=d.items;return S.cats}
async function createCategory(name){const d=await api('/api/categories',{method:'POST',body:{name}});S.cats=d.items;toast(`Category \u201c${d.name}\u201d added.`);return d.name}
function catOptions(none){
  const o=[];if(none!==undefined)o.push({v:'',l:none});
  (S.cats||[]).filter(c=>c.kind!=='default').forEach(c=>o.push({v:c.name,l:c.name,h:c.count?`${c.count} product${c.count>1?'s':''}`:'',g:'Your categories'}));
  (S.cats||[]).filter(c=>c.kind==='default').forEach(c=>o.push({v:c.name,l:c.name,g:'Suggestions'}));
  return o}
function catFilterOptions(){
  const o=[{v:'',l:'All categories'},{v:'__none__',l:'No category'}];
  (S.cats||[]).filter(c=>c.count>0).forEach(c=>o.push({v:c.name,l:c.name,h:String(c.count)}));
  return o}

/* ---------- passwords ---------- */
const pwField=(id,name,ac)=>`<div class="pw"><input class="input" id="${id}" type="password" name="${name}" autocomplete="${ac}" required maxlength="200"><button type="button" data-act="pw-toggle" aria-label="Show password">${ico('eye')}</button></div>`;
function pwScore(p){if(!p)return 0;if(p.length<BOOT.minPassword)return -1;let s=1;if(p.length>=14)s++;if(/[a-z]/.test(p)&&/[A-Z]/.test(p))s++;if(/\d/.test(p)&&/[^A-Za-z0-9]/.test(p))s++;return s}
CALC.pw=f=>{const inp=$('input[data-pwmeter]',f);const bar=$('.meter i',f);const txt=$('.meter-t',f);if(!inp||!bar||!txt)return;
  const s=pwScore(inp.value);const m={'-1':[18,'var(--bad)',`Too short. Use at least ${BOOT.minPassword} characters.`],0:[0,'var(--bad)',`Use at least ${BOOT.minPassword} characters.`],1:[40,'var(--bad)','Weak. Add more words or characters.'],2:[62,'var(--gold)','Okay. A longer password is safer.'],3:[82,'var(--ok)','Good.'],4:[100,'var(--ok)','Strong.']}[s];
  bar.style.width=m[0]+'%';bar.style.background=m[1];txt.textContent=m[2]};

async function lookupRef(code){code=cleanRef(code);if(code.length<5)return null;try{const d=await api('/api/referral/check?code='+encodeURIComponent(code));return d.valid?d:null}catch(e){return null}}
LIVE.refcode=async v=>{
  const h=$('#refhint');if(!h)return;const c=cleanRef(v);
  if(!c){h.className='hint';h.textContent='';return}
  const info=await lookupRef(c);const h2=$('#refhint');if(!h2)return;
  if(info){h2.className='hint ok';h2.textContent=`Invited by ${info.business}. You get ${info.bonus_days} extra free days.`}
  else{h2.className='hint bad';h2.textContent=c.length<5?'Keep typing\u2026':'That code is not valid.'}};
function announceRewards(list){
  if(!list||!list.length)return;const days=list.reduce((a,x)=>a+x.days,0);
  const who=list.length===1?list[0].name:`${list.length} shops you referred`;
  setTimeout(()=>toast(`${who} hit the sales target. You earned ${days} free days.`),900);
  api('/api/referrals/seen',{method:'POST',body:{}}).catch(()=>{})}
function refreshTrial(){const s=$('.biz small');if(s&&S.biz)s.textContent=trialLine(S.biz)}

/* ---------- landing + auth ---------- */
function renderLanding(){
  const feats=[['orders','Orders that track payment','See at a glance what is paid, part-paid or still pending, and record each payment as it comes in.'],['stock','Stock that warns you','Set an alert level per product. Oja Loom tells you what is running low before a customer asks for it.'],['debts','Debts you can chase','Every unpaid balance in one list, with a ready-written WhatsApp reminder for each customer.'],['receipts','Receipts you can send','A clean receipt link for every order. Print it, save it as a PDF, or send it on WhatsApp.'],['storefront','A storefront link','Share one page with your products, prices and categories. Customers order straight to your WhatsApp.'],['reports','Reports without the jargon','Sales, best sellers, top customers and estimated profit for any dates you choose.']];
  $('#root').innerHTML=`<div class="l-hero"><header class="l-top"><div class="brand">${MARK}Oja Loom</div><div class="l-top-a"><button type="button" class="btn lite" data-act="theme" aria-label="Switch colour theme">${ico(document.documentElement.dataset.theme==='dark'?'sun':'moon')}</button><button type="button" class="btn lite l-login" data-act="auth" data-mode="login">Log in</button><button type="button" class="btn gold" data-act="auth" data-mode="signup">Start free</button></div></header>
<div class="l-in"><div class="l-copy">${S.refInfo?`<div class="l-invite">${ico('gift')}<span><b>${esc(S.refInfo.business)}</b> invited you. Sign up through their link and get ${S.refInfo.bonus_days} extra free days.</span></div>`:''}<h1>Know who paid, who owes, and what is left on the shelf.</h1><p>Oja Loom keeps your orders, stock, customers and receipts in one place. It is built for sellers who take orders on WhatsApp, Instagram and in the shop.</p><div class="l-cta"><button type="button" class="btn gold" data-act="auth" data-mode="signup">Create your business</button><button type="button" class="btn lite" data-act="auth" data-mode="login">Log in</button></div><small>30 days free trial. No card needed. Your data stays on your own server.</small></div>
<div class="l-art" aria-hidden="true"><div class="slip"><h3>Ada Fabrics</h3><div class="s-m">Receipt OJL-20261002-4821</div><div class="s-r first"><span>Ankara 6 yards \u00d7 2</span><span class="num">\u20a624,000</span></div><div class="s-r"><span>Lace fabric \u00d7 1</span><span class="num">\u20a618,500</span></div><div class="s-t"><span>Total</span><span class="num">\u20a642,500</span></div><div class="s-b"><span>Balance due</span><span class="num">\u20a612,500</span></div></div><div class="wa">Hello Bisi, a reminder that your balance for OJL-20261002-4821 is \u20a612,500. Thank you.<small>10:42</small></div></div></div></div>
<section class="l-sec"><h2>Everything a small shop needs to stay on top of sales.</h2><div class="feat">${feats.map(f=>`<div>${ico(f[0])}<h3>${f[1]}</h3><p>${f[2]}</p></div>`).join('')}</div></section>
<section class="l-end"><div><h2>Set up your first product in two minutes.</h2><button type="button" class="btn gold" data-act="auth" data-mode="signup">Start free</button></div></section><footer class="l-foot">Oja Loom \u00b7 Built for Nigerian businesses \u00b7 <a href="${U('/terms')}" target="_blank" rel="noopener">Terms of Service</a></footer>`}
// Nigerian phone numbers are 11 digits, like 08031234567. Typing or pasting is tidied as you go (+234 803... becomes 0803...).
const ngPhoneFix=v=>{let d=String(v||'').replace(/\D/g,'');if(d.startsWith('234')&&d.length>=13)d='0'+d.slice(3);return d.slice(0,d.startsWith('234')?13:11)};
const phoneLocal=p=>{p=String(p||'').replace(/\D/g,'');if(p.startsWith('234'))return '0'+p.slice(3);if(p.length===10&&/^[789]/.test(p))return '0'+p;return p};
function showAuth(mode='login'){
  const su=mode==='signup';if(layers.length){while(layers.length>1)closeLayer();closeTop();S.skipPush=true}
  const w=dialog(`<div class="row-b"><h2>${su?'Create your Oja Loom':'Welcome back'}</h2><button type="button" class="btn ghost icon" data-act="close-layer" aria-label="Close">${ico('x')}</button></div>
<div class="tabs2" role="tablist"><button type="button" role="tab" aria-selected="${!su}" data-act="auth-tab" data-mode="login">Log in</button><button type="button" role="tab" aria-selected="${su}" data-act="auth-tab" data-mode="signup">Sign up</button></div>
<form data-form="auth" data-mode="${mode}"${su?' data-calc="pw"':''}><div class="ferr"></div>
${su?`<div class="cols2"><div class="field"><label for="a-name">Your name</label><input class="input" id="a-name" name="owner_name" required maxlength="120" autocomplete="name"></div><div class="field"><label for="a-biz">Business name</label><input class="input" id="a-biz" name="business_name" required maxlength="160" autocomplete="organization"></div></div>
<div class="cols2"><div class="field"><label>Business type</label>${dd({name:'category',options:BOOT.categories.map(c=>({v:c,l:c})),placeholder:'Choose a type',label:'Business type'})}</div><div class="field"><label for="a-phone">Phone number</label><input class="input" id="a-phone" name="phone" inputmode="tel" required maxlength="20" pattern="0[789][01][0-9]{8}" title="11-digit Nigerian number, like 08031234567" data-ngphone placeholder="08031234567" autocomplete="tel"></div></div>`:''}
<div class="field"><label for="a-email">Email</label><input class="input" id="a-email" type="email" name="email" required autocomplete="email" inputmode="email" maxlength="254"></div>
<div class="field"><label for="a-pw">Password</label>${pwField('a-pw','password',su?'new-password':'current-password').replace('<input ','<input data-pwmeter ')}${su?`<div class="meter"><i></i></div><div class="meter-t">Use at least ${BOOT.minPassword} characters.</div>`:''}</div>
${su?`<div class="field"><label for="a-ref">Referral code <span class="muted">(optional)</span></label><input class="input" id="a-ref" name="referral_code" maxlength="14" autocomplete="off" autocapitalize="characters" spellcheck="false" placeholder="e.g. K7F2M9Q" value="${esc(S.ref)}" data-live="refcode"><div class="hint" id="refhint"></div></div>`:''}
${su?`<label class="check"><input type="checkbox" name="accept_terms" value="1" required><span>I have read and agree to the <a href="${U('/terms')}" target="_blank" rel="noopener">Terms of Service</a>.</span></label>`:''}
<button class="btn primary block" type="submit">${su?'Create my business':'Log in'}</button></form>`,su?'Sign up':'Log in');
  w.classList.add('auth-wrap');$('.dlg',w).classList.add('auth');
  if(su&&S.ref)LIVE.refcode(S.ref)}
FORMS.auth=async f=>{
  const mode=f.dataset.mode;const b=Object.fromEntries(new FormData(f));const btn=$('button[type=submit]',f);const label=btn.textContent;busy(btn,true,'Working\u2026');
  try{const d=await api('/api/'+mode,{method:'POST',body:b});S.me=d.user;S.biz=d.business;S.csrf=d.csrf;S.cats=null;clearRef();closeLayers();render();
    toast(d.referral?`Welcome to Oja Loom. You got ${d.referral.bonus_days} extra free days from ${d.referral.referrer}.`:mode==='signup'?'Welcome to Oja Loom. Your business is ready.':'Welcome back.');announceRewards(d.rewards);setTimeout(()=>{S.termsAsked=false;askTerms()},1000)}
  catch(err){formErr(f,err.message)}finally{busy(btn,false,label)}};
async function logout(all){
  try{await api(all?'/api/account/logout-all':'/api/logout',{method:'POST',body:{}})}catch(e){}
  S.me=S.biz=S.csrf=null;S.cats=null;closeLayers();hIndex=0;try{history.replaceState({i:0},'',location.pathname)}catch(e){}render()}

/* ---------- app shell + router ---------- */
function trialLine(b){
  const a=b.access;
  if(a){const dl=a.days_left==null?'':` \u00b7 ${a.days_left} day${a.days_left===1?'':'s'} left`;
    if(a.state==='pro')return 'Oja Loom Pro'+dl;if(a.state==='trial')return 'Free trial'+dl;return 'Free plan'}
  if(b.subscription_status==='trialing'){const d=Math.ceil((new Date(b.trial_end)-Date.now())/864e5);return d>0?`Free trial \u00b7 ${d} day${d===1?'':'s'} left`:'Trial ended'}return `${b.plan} plan`}

function planLabel(b){const a=b.access;if(a)return a.state==='pro'?'Oja Loom Pro':a.state==='trial'?'Free trial':'Free plan';return String(b.plan||'').toUpperCase()}
const avatar=b=>b.has_logo?`<span class="avatar"><img src="${esc(b.logo_url)}" alt=""></span>`:`<span class="avatar">${initial(b.name)}</span>`;
function navHtml(){return NAV.map(g=>`${g[0]?`<div class="nav-g">${g[0]}</div>`:''}${g[1].map(v=>`<button type="button" class="nav-i" data-act="nav" data-to="${v}" data-view="${v}">${ico(v)}<span>${LABEL[v]}</span></button>`).join('')}`).join('')}
function renderApp(){
  const b=S.biz,dark=document.documentElement.dataset.theme==='dark';
  $('#root').innerHTML=`<div class="app"><aside class="side"><div class="brand">${MARK}Oja Loom</div><div class="biz">${avatar(b)}<div><b>${esc(b.name)}</b><small>${esc(trialLine(b))}</small></div></div>${upgradeChip(b)}<nav class="nav" aria-label="Main">${navHtml()}</nav><div class="side-foot"><div class="who"><b>${esc(S.me.owner_name||'You')}</b><span>${esc(S.me.email)}</span></div><button type="button" class="btn icon sm" data-act="logout" aria-label="Log out" title="Log out">${ico('logout')}</button></div></aside>
<div class="main"><header class="bar"><div class="brand">${MARK}Oja Loom</div><div class="bar-r"><button type="button" class="btn icon ghost" data-act="theme" aria-label="Switch colour theme" id="themebtn">${ico(dark?'sun':'moon')}</button><button type="button" class="btn primary" data-act="new-menu" aria-haspopup="menu" aria-expanded="false">${ico('plus')}<span>New</span></button></div></header><main id="page" class="page" tabindex="-1"></main></div>
<nav class="tabs" aria-label="Main">${['dashboard','orders','products','customers'].map(v=>`<button type="button" data-act="nav" data-to="${v}" data-view="${v}">${ico(v)}<span>${LABEL[v]}</span></button>`).join('')}<button type="button" data-act="more" data-view="more">${ico('more')}<span>More</span></button></nav></div>`}
function parseRoute(){
  const h=location.hash.replace(/^#\/?/,'');const [p,qs]=h.split('?');const [view,id]=(p||'').split('/');const q={};new URLSearchParams(qs||'').forEach((v,k)=>{q[k]=v});
  return{view:VIEWS.includes(view)?view:'dashboard',id:id||'',q}}
function go(path){
  if(S.busy>0){S.pendingGo=path;return}
  const target='#/'+path;
  if(location.hash===target){showRoute();return}
  try{history.pushState({i:++hIndex},'',target)}catch(e){location.hash=target;return}
  showRoute()}
function flushNav(){
  if(S.pendingGo){const p=S.pendingGo;S.pendingGo=null;go(p);return}
  if(S.me&&location.hash!==S.shownHash)showRoute()}
function showRoute(){
  if(!S.me)return;const r=parseRoute();S.route=r;S.nav++;S.shownHash=location.hash;
  $$('[data-view]').forEach(b=>{if(b.dataset.view===r.view)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current')});
  scrollTo(0,0);document.title=`${LABEL[r.view]} \u00b7 ${S.biz.name} \u00b7 Oja Loom`;
  const fn=LOAD[r.view];if(fn)fn(r);S.back=false}
function render(){
  if(!S.me){document.title='Oja Loom \u2014 run your shop without the stress';renderLanding();return}
  renderApp();showRoute()}

/* ---------- global events ---------- */
document.addEventListener('click',e=>{
  const t=e.target;
  if(t.classList&&t.classList.contains('wrap')&&layers[layers.length-1]===t){closeLayer();return}
  const opt=t.closest&&t.closest('#ddlayer .dd-opt[data-i]');
  if(opt){ddPick(+opt.dataset.i);return}
  const el=t.closest&&t.closest('[data-act]');if(!el)return;
  const fn=ACT[el.dataset.act];if(fn)fn(el,e)});
document.addEventListener('mouseover',e=>{
  const o=e.target.closest&&e.target.closest('#ddlayer .dd-opt[data-i]');const st=ddOpenState;
  if(!o||!st||st.kind!=='select')return;const i=+o.dataset.i;if(i===st.hl)return;st.hl=i;$$('#ddlayer .dd-opt').forEach(x=>x.classList.toggle('hl',x===o))});
document.addEventListener('submit',e=>{const f=e.target.closest('form[data-form]');if(!f)return;e.preventDefault();const fn=FORMS[f.dataset.form];if(fn)fn(f)});
document.addEventListener('input',e=>{
  const t=e.target;
  if(t.dataset&&t.dataset.ngphone!==undefined){const v=ngPhoneFix(t.value);if(v!==t.value)t.value=v}
  if(t.classList&&t.classList.contains('dd-q')&&ddOpenState){ddOpenState.q=t.value;ddOpenState.hl=0;ddRender();return}
  const lv=t.closest&&t.closest('[data-live]');if(lv){clearTimeout(lv._t);lv._t=setTimeout(()=>{const fn=LIVE[lv.dataset.live];if(fn)fn(lv.value.trim())},260)}
  const c=t.closest&&t.closest('[data-calc]');if(c){const fn=CALC[c.dataset.calc];if(fn)fn(c)}});
document.addEventListener('keydown',e=>{
  if(ddOpenState&&ddKey(e))return;
  if(e.key==='Escape'&&layers.length){e.preventDefault();closeLayer();return}
  if(e.key==='Tab'&&layers.length)trapTab(e);
  if((e.key==='Enter'||e.key===' ')&&e.target.matches&&e.target.matches('.tr[data-act]')){e.preventDefault();e.target.click()}});
window.addEventListener('popstate',e=>{
  const st=e.state||{};hIndex=typeof st.i==='number'?st.i:0;
  if(S.busy>0){S.busy--;if(S.busy===0){clearTimeout(S.busyT);flushNav()}return}
  const L=st.L||0;
  if(layers.length>L){while(layers.length>L)closeTop();return}
  if(L>layers.length){histBack(L-layers.length);return}
  if(S.me){S.back=true;showRoute()}});
window.addEventListener('resize',()=>{if(ddOpenState)ddClose()});

/* ---------- shared actions ---------- */
ACT['close-layer']=()=>closeLayer();
ACT.back=el=>{if(hIndex>0)history.back();else go(el.dataset.to||'dashboard')};
ACT['dd-open']=el=>ddOpen(el.dataset.id);
ACT['dd-close']=()=>ddClose(true);
ACT['confirm-yes']=el=>{const w=el.closest('.wrap');const r=w._confirm;w._confirm=null;closeLayer();if(r)r(true)};
ACT['confirm-no']=()=>closeLayer();
ACT.nav=el=>{closeLayers();go(el.dataset.to)};
ACT.theme=()=>{const t=document.documentElement.dataset.theme==='dark'?'light':'dark';setTheme(t,true);const b=$('#themebtn');if(b)b.innerHTML=ico(t==='dark'?'sun':'moon');$$('[data-act=theme]').forEach(x=>{if(x.id!=='themebtn')x.innerHTML=ico(t==='dark'?'sun':'moon')})};
ACT.auth=el=>showAuth(el.dataset.mode||'login');
ACT['auth-tab']=el=>showAuth(el.dataset.mode);
ACT['pw-toggle']=el=>{const i=el.previousElementSibling;const show=i.type==='password';i.type=show?'text':'password';el.innerHTML=ico(show?'eyeoff':'eye');el.setAttribute('aria-label',show?'Hide password':'Show password')};
ACT.logout=async()=>{if(await confirmBox({title:'Log out?',text:'Are you sure you want to log out of Oja Loom?',ok:'Log out'}))logout(false)};
ACT['new-menu']=el=>{if(ddOpenState&&ddOpenState.kind==='menu'){ddClose(true);return}popMenu(el,[{icon:'orders',label:'New order',run:'new-order'},{icon:'products',label:'Add product',run:'new-product'},{icon:'customers',label:'Add customer',run:'new-customer'},{icon:'expenses',label:'Add expense',run:'new-expense'}])};
ACT['menu-run']=el=>{const run=el.dataset.run;ddClose();const fn=ACT[run];if(fn)fn(el)};
ACT.more=()=>{const w=dialog(`<div class="row-b"><h2>More</h2><button type="button" class="btn ghost icon" data-act="close-layer" aria-label="Close">${ico('x')}</button></div><div class="more-list">${['debts','receipts','storefront','reports','expenses','history','billing','referrals','settings'].map(v=>`<button type="button" class="nav-i" data-act="nav" data-to="${v}">${ico(v)}<span>${LABEL[v]}</span></button>`).join('')}${SUPPORT_WA?`<a class="nav-i" href="${esc(supportLink())}" target="_blank" rel="noopener noreferrer">${ico('chat')}<span>Chat with support</span></a>`:''}<button type="button" class="nav-i" data-act="theme">${ico('sun')}<span>Switch theme</span></button><button type="button" class="nav-i" data-act="logout">${ico('logout')}<span>Log out</span></button></div>`,'More')};
ACT.copy=async el=>{const text=el.dataset.text||'';try{await navigator.clipboard.writeText(text);toast('Link copied.')}catch(e){const i=$('input[readonly]',el.parentElement);if(i){i.select();try{document.execCommand('copy');toast('Link copied.')}catch(x){toast('Press Ctrl+C to copy the link.',true)}}}};

/* ---------- images ---------- */
const webpOk=()=>{try{return document.createElement('canvas').toDataURL('image/webp').startsWith('data:image/webp')}catch(e){return false}};
async function toDataUrl(file,kind){
  if(!/^image\/(png|jpeg|webp|gif)$/.test(file.type))throw new Error('Please choose a PNG, JPEG, WebP or GIF image.');
  if(file.size>12*1024*1024)throw new Error('That image is too big. Choose one under 12 MB.');
  let bmp;
  try{bmp=await createImageBitmap(file)}catch(e){bmp=await new Promise((res,rej)=>{const fr=new FileReader();fr.onload=()=>{const im=new Image();im.onload=()=>res(im);im.onerror=()=>rej(new Error('That image could not be read.'));im.src=fr.result};fr.onerror=()=>rej(new Error('That image could not be read.'));fr.readAsDataURL(file)})}
  const w0=bmp.width||bmp.naturalWidth,h0=bmp.height||bmp.naturalHeight;const max=kind==='logo'?360:900;const k=Math.min(1,max/Math.max(w0,h0));
  const w=Math.max(1,Math.round(w0*k)),h=Math.max(1,Math.round(h0*k));
  const cv=document.createElement('canvas');cv.width=w;cv.height=h;const cx=cv.getContext('2d');
  if(kind!=='logo'){cx.fillStyle='#fff';cx.fillRect(0,0,w,h)}
  cx.drawImage(bmp,0,0,w,h);
  const mime=kind==='logo'?'image/png':'image/jpeg';let out='',q=.85;
  for(let i=0;i<4;i++){out=cv.toDataURL(mime,q);if(out.length<1900000)break;q-=.15}
  if(out.length>2900000)throw new Error('That image is still too large after resizing. Try a smaller one.');
  return out}
const imageField=(url,kind)=>{const name=kind==='logo'?'logo_data':'image_data';const word=kind==='logo'?'logo':'photo';
  return `<div class="field"><span class="lbl">${kind==='logo'?'Logo':'Photo'} <span class="muted">(optional)</span></span><label class="drop${url?' has':''}" data-drop><input class="sr" type="file" accept="image/png,image/jpeg,image/webp,image/gif" data-file="${kind}" aria-label="Choose ${word}"><input type="hidden" name="${name}" value="" disabled><span class="empty-t">${ico('image')}<span><b>Add a ${word}</b><span>Drop an image here or tap to choose</span></span></span>${url?`<img src="${esc(url)}" alt="">`:''}</label><div class="imgrow${url?'':' hidden'}"><button type="button" class="btn sm ghost" data-act="img-clear">Remove ${word}</button></div><span class="hint">Images are resized for you automatically.</span></div>`};
async function handleImage(input,file){
  const zone=input.closest('[data-drop]');const hid=$('input[type=hidden]',zone);
  try{const url=await toDataUrl(file,input.dataset.file);hid.value=url;hid.disabled=false;let img=$('img',zone);if(!img){img=document.createElement('img');img.alt='';zone.appendChild(img)}img.src=url;zone.classList.add('has');const row=zone.parentElement.querySelector('.imgrow');if(row)row.classList.remove('hidden')}
  catch(e){toast(e.message,true)}}
document.addEventListener('change',e=>{const f=e.target.closest&&e.target.closest('input[data-file]');if(f&&f.files[0]){handleImage(f,f.files[0]);f.value=''}});
document.addEventListener('dragover',e=>{const z=e.target.closest&&e.target.closest('[data-drop]');if(z){e.preventDefault();z.classList.add('over')}});
document.addEventListener('dragleave',e=>{const z=e.target.closest&&e.target.closest('[data-drop]');if(z)z.classList.remove('over')});
document.addEventListener('drop',e=>{const z=e.target.closest&&e.target.closest('[data-drop]');if(!z)return;e.preventDefault();z.classList.remove('over');const f=e.dataTransfer&&e.dataTransfer.files[0];if(f)handleImage($('input[data-file]',z),f)});
ACT['img-clear']=el=>{const field=el.closest('.field');const zone=$('[data-drop]',field);const hid=$('input[type=hidden]',zone);hid.value='';hid.disabled=false;const img=$('img',zone);if(img)img.remove();zone.classList.remove('has');el.parentElement.classList.add('hidden')};


/* =========================== DASHBOARD =========================== */
function greeting(){const h=new Date().getHours();const n=(S.me.owner_name||'').trim().split(/\s+/)[0];return (h<12?'Good morning':h<17?'Good afternoon':'Good evening')+(n?', '+n:'')}
LOAD.dashboard=async()=>{
  const n=S.nav;
  setPage(pageHead(greeting(),'Here is how the shop is doing.',`<button type="button" class="btn primary" data-act="new-order">${ico('plus')}New order</button>`)+`<div class="kpis">${[1,2,3,4].map(()=>'<div class="kpi"><div class="sk" style="height:58px"></div></div>').join('')}</div>`);
  try{
    const d=await api('/api/dashboard');if(n!==S.nav)return;
    const bars=d.sales_by_day||[];const max=Math.max(1,...bars.map(x=>x.total));const sum=bars.reduce((a,x)=>a+x.total,0);
    const fresh=!d.total_customers&&!d.month_sales&&!d.today_orders&&!d.outstanding_debt;
    const att=[['orders','Orders still open',d.pending_orders,'orders'],['stock','Low on stock',d.low_stock,'products?stock=low'],['stock','Out of stock',d.out_of_stock,'products?stock=out'],['debts','Money owed to you',money(d.outstanding_debt,true),'debts']].concat(d.overdue_count?[['debts','Debts past their due date',d.overdue_count,'debts?filter=overdue']]:[],[['customers','Customers',d.total_customers,'customers']]);
    setPage(pageHead(greeting(),'Here is how the shop is doing.',`<button type="button" class="btn primary" data-act="new-order">${ico('plus')}New order</button>`)
    +`<div class="kpis"><div class="kpi"><div class="k">Today\u2019s sales</div><div class="v num">${money(d.today_sales,true)}</div><div class="f">${d.today_orders} order${d.today_orders===1?'':'s'} today</div></div><div class="kpi"><div class="k">This month</div><div class="v num">${money(d.month_sales,true)}</div><div class="f">Completed orders</div></div><div class="kpi owed"><div class="k">Owed to you</div><div class="v num">${money(d.outstanding_debt,true)}</div><div class="f">${d.overdue_count?money(d.overdue_total,true)+' past due':'Unpaid balances'}</div></div><div class="kpi"><div class="k">${d.month_expenses>0?'Net profit':'Estimated profit'}</div><div class="v num">${money(d.month_expenses>0?d.month_net:d.month_profit,true)}</div><div class="f">${d.month_expenses>0?'After '+money(d.month_expenses,true)+' expenses':'This month'}</div></div></div>`
    +(fresh?`<div class="panel" style="margin-top:18px"><div class="panel-h"><h2>Start here</h2></div><div class="panel-b"><p class="muted" style="margin:0 0 16px">Add what you sell, then record your first order. Sales figures appear once an order is marked Completed.</p><div class="phead-a"><button type="button" class="btn primary" data-act="new-product">${ico('products')}Add a product</button><button type="button" class="btn" data-act="new-customer">${ico('customers')}Add a customer</button></div></div></div>`:'')
    +`<div class="cols"><section class="panel"><div class="panel-h"><h2>Sales, last 14 days</h2><span class="muted num">${money(sum,true)}</span></div><div class="panel-b"><div class="chart" role="img" aria-label="Daily sales for the last 14 days">${bars.map(x=>`<div class="bar-c${x.total===max&&max>1?' top':''}" style="--h:${Math.max(2,x.total/max*100).toFixed(1)}%" data-tip="${esc(x.date)} \u00b7 ${money(x.total,true)}"><i></i></div>`).join('')}</div><div class="axis"><span>${esc(bars[0]?bars[0].date:'')}</span><span>${esc(bars.length?bars[bars.length-1].date:'')}</span></div></div></section>
<section class="panel"><div class="panel-h"><h2>Needs attention</h2></div>${att.map(a=>`<button type="button" class="att" data-act="nav" data-to="${a[3]}"><span>${a[1]}</span><span class="r"><b class="num">${a[2]}</b>${ico('chev')}</span></button>`).join('')}</section></div>
<section class="panel" style="margin-top:18px"><div class="panel-b row-b"><div><b>Earn free days</b><div class="muted">Invite a shop owner. When their shop hits its sales target, you get ${BOOT.referral.referrer} free days. You can earn up to ${BOOT.referral.max} rewards, and each one is tougher than the last.</div></div><button type="button" class="btn soft" data-act="nav" data-to="referrals">${ico('gift')}Invite</button></div></section>`)
  }catch(e){if(n===S.nav)setPage(alertBox(e.message))}};

/* =========================== PRODUCTS =========================== */
LOAD.products=async r=>{
  const n=S.nav;if(!S.back)S.pf={q:'',cat:r.q.category||'',stock:r.q.stock||'',catCfg:null};
  setPage(pageHead('Products','\u2026',`<button type="button" class="btn primary" data-act="new-product">${ico('plus')}Add product</button>`)+skel(5));
  try{await loadCats()}catch(e){S.cats=S.cats||[]}
  if(n!==S.nav)return;
  const catCfg={sm:true,value:S.pf.cat,label:'Filter by category',options:catFilterOptions(),onChange:v=>{S.pf.cat=v;refreshProducts()}};S.pf.catCfg=catCfg;
  const stockCfg={sm:true,value:S.pf.stock,label:'Filter by stock level',options:[{v:'',l:'All stock levels'},{v:'in',l:'In stock'},{v:'low',l:'Low stock'},{v:'out',l:'Out of stock'}],onChange:v=>{S.pf.stock=v;refreshProducts()}};
  setPage(pageHead('Products','\u2026',`<button type="button" class="btn primary" data-act="new-product">${ico('plus')}Add product</button>`)
    +`<div class="tools"><div class="search">${ico('search')}<input class="input" type="search" placeholder="Search name, SKU or category" data-live="products" aria-label="Search products" maxlength="100" value="${esc(S.pf.q)}"></div>${dd(catCfg)}${dd(stockCfg)}</div><div id="plist">${skel(5)}</div>`);
  refreshProducts()};
LIVE.products=v=>{S.pf.q=v;refreshProducts()};
async function refreshProducts(){
  const n=S.nav;if(!$('#plist'))return;
  const p=new URLSearchParams();if(S.pf.q)p.set('search',S.pf.q);if(S.pf.cat)p.set('category',S.pf.cat);if(S.pf.stock)p.set('stock',S.pf.stock);p.set('limit','500');
  try{
    const d=await api('/api/products?'+p);if(n!==S.nav||!$('#plist'))return;
    S.map.products=new Map(d.items.map(x=>[x.id,x]));const filtered=!!(S.pf.q||S.pf.cat||S.pf.stock);
    const sub=$('.phead p');if(sub)sub.textContent=filtered?`${d.items.length} match${d.items.length===1?'':'es'}`:`${d.items.length} product${d.items.length===1?'':'s'}`;
    $('#plist').innerHTML=d.items.length?`<section class="panel"><div class="tbl" style="--cols:minmax(0,2.6fr) minmax(0,1.3fr) 130px 150px 120px;--cols-md:minmax(0,2.4fr) 120px 150px"><div class="tr th"><div>Product</div><div class="hide-md">Category</div><div>Price</div><div>Stock</div><div class="hide-md right">Profit per unit</div></div>${d.items.map(x=>`<div class="tr" data-act="edit-product" data-id="${esc(x.id)}" role="button" tabindex="0" aria-label="Edit ${esc(x.name)}"><div class="cell-main">${x.has_image?`<img class="thumb" src="${esc(x.image_url)}" alt="" loading="lazy">`:`<span class="thumb">${initial(x.name)}</span>`}<div><b>${esc(x.name)}</b><small>${x.sku?esc(x.sku):'No SKU'}${x.active?'':' \u00b7 Inactive'}</small></div></div><div class="hide-md" data-label="Category">${x.category?`<span class="tag">${esc(x.category)}</span>`:'<span class="muted">\u2014</span>'}</div><div class="num" data-label="Price">${money(x.selling_price)}</div><div data-label="Stock">${pill(x.stock_state)} <span class="muted num">${x.stock_quantity}</span></div><div class="hide-md right num" data-label="Profit per unit">${money(x.profit_per_unit)}</div></div>`).join('')}</div></section>`
      :`<section class="panel">${filtered?emptyBox('search','Nothing matches those filters','Try a different search or clear a filter.'):emptyBox('products','No products yet','Add what you sell to start taking orders and tracking stock.',`<button type="button" class="btn primary" data-act="new-product">${ico('plus')}Add your first product</button>`)}</section>`
  }catch(e){if(n===S.nav)$('#plist').innerHTML=alertBox(e.message)}}
async function refreshCatsEverywhere(){try{await loadCats(true)}catch(e){return}if(S.pf.catCfg)S.pf.catCfg.options=catFilterOptions()}
CALC.margin=f=>{
  const sp=parseFloat(f.elements.selling_price.value),cp=parseFloat(f.elements.cost_price.value);const el=$('[data-margin]',f);if(!el)return;
  if(isNaN(sp)||isNaN(cp)){el.className='margin';el.textContent='Profit per unit appears here once you enter both prices.';return}
  const pr=sp-cp;const pct=sp>0?Math.round(pr/sp*100):0;
  if(pr<0){el.className='margin bad';el.innerHTML=`You would lose <b>${money(-pr)}</b> on every sale.`}else{el.className='margin';el.innerHTML=`Profit per unit <b>${money(pr)}</b> \u00b7 ${pct}% margin`}};
async function openProduct(id){
  const x=id&&S.map.products?S.map.products.get(id):null;
  try{await loadCats()}catch(e){S.cats=S.cats||[]}
  const neg=!!(S.biz&&S.biz.allow_negative_inventory);
  const catCfg={name:'category',value:x?x.category:'',placeholder:'Choose a category',emptyPh:true,label:'Category',search:true,options:catOptions('No category'),rebuild:()=>catOptions('No category'),create:{noun:'category',fn:createCategory}};
  const body=`<form id="f-product" data-form="product" data-id="${esc(id||'')}" data-calc="margin"><div class="ferr"></div>
<div class="field"><label for="p-name">Product name</label><input class="input" id="p-name" name="name" required maxlength="180" value="${esc(x?x.name:'')}" placeholder="e.g. Ankara fabric, 6 yards"></div>
<div class="field"><label>Category</label>${dd(catCfg)}<span class="hint">Pick one from the list, or type a new name to add your own.</span></div>
<div class="field"><label for="p-desc">Description <span class="muted">(optional)</span></label><textarea class="textarea" id="p-desc" name="description" maxlength="2500" placeholder="Size, colour, material\u2026">${esc(x?x.description:'')}</textarea></div>
<div class="sect">Price and stock</div>
<div class="cols2"><div class="field"><label for="p-sp">Selling price</label><div class="ig"><span>\u20a6</span><input class="input" id="p-sp" name="selling_price" type="number" step="0.01" min="0" inputmode="decimal" required value="${x?x.selling_price:''}"></div></div><div class="field"><label for="p-cp">Cost price</label><div class="ig"><span>\u20a6</span><input class="input" id="p-cp" name="cost_price" type="number" step="0.01" min="0" inputmode="decimal" required value="${x?x.cost_price:''}"></div></div></div>
<div class="margin" data-margin></div>
<div class="cols2"><div class="field"><label for="p-stock">Stock quantity</label><input class="input" id="p-stock" name="stock_quantity" type="number" step="1"${neg?'':' min="0"'} inputmode="numeric" required value="${x?x.stock_quantity:0}"></div><div class="field"><label for="p-low">Alert me at</label><input class="input" id="p-low" name="low_stock_threshold" type="number" step="1" min="0" inputmode="numeric" required value="${x?x.low_stock_threshold:5}"><span class="hint">Shows as low stock at or below this number.</span></div></div>
${x?`<div class="phead-a" style="margin:-4px 0 6px"><button type="button" class="btn sm" data-act="adjust-stock" data-id="${esc(id)}">${ico('products')}Adjust stock with a reason</button><button type="button" class="btn sm" data-act="prod-history" data-id="${esc(id)}">${ico('history')}Edit history</button></div>`:''}
<div class="sect">Details</div>
<div class="cols2"><div class="field"><label for="p-sku">SKU <span class="muted">(optional)</span></label><input class="input" id="p-sku" name="sku" maxlength="100" value="${esc(x?x.sku:'')}"></div><div class="field"><label>Status</label>${dd({name:'active',value:x&&!x.active?'0':'1',label:'Status',options:[{v:'1',l:'Active',h:'On sale'},{v:'0',l:'Inactive',h:'Hidden'}]})}</div></div>
${imageField(x&&x.has_image?x.image_url:'','product')}</form>`;
  const w=drawer({title:x?'Edit product':'Add product',body,foot:`${x?`<button type="button" class="btn danger" data-act="del-product" data-id="${esc(id)}">${ico('trash')}Delete</button>`:'<span></span>'}<div class="grow"><button type="button" class="btn" data-act="close-layer">Cancel</button><button class="btn primary" type="submit" form="f-product">${x?'Save changes':'Add product'}</button></div>`});
  CALC.margin($('form',w))}
FORMS.product=async f=>{
  const id=f.dataset.id;const b=Object.fromEntries(new FormData(f));b.active=b.active!=='0';
  const btn=$('button[type=submit][form='+f.id+']');const label=btn?btn.textContent:'';busy(btn,true,'Saving\u2026');
  try{await api('/api/products'+(id?'/'+id:''),{method:id?'PUT':'POST',body:b});closeLayers();toast(id?'Product saved.':'Product added.');await refreshCatsEverywhere();if(S.route.view==='products')refreshProducts();else showRoute()}
  catch(e){formErr(f,e.message)}finally{busy(btn,false,label)}};
ACT['new-product']=()=>openProduct(null);
ACT['edit-product']=el=>openProduct(el.dataset.id);
ACT['del-product']=async el=>{
  const id=el.dataset.id;const x=S.map.products&&S.map.products.get(id);
  if(!await confirmBox({title:'Delete this product?',text:`${x?x.name:'This product'} will be removed. A product that is already on an order cannot be deleted; set it to Inactive instead.`,ok:'Delete product',danger:true}))return;
  try{await api('/api/products/'+id,{method:'DELETE',body:{}});closeLayers();toast('Product deleted.');await refreshCatsEverywhere();if(S.route.view==='products')refreshProducts()}catch(e){toast(e.message,true)}};

/* =========================== CUSTOMERS =========================== */
LOAD.customers=async()=>{
  if(!S.back)S.cf={q:''};
  setPage(pageHead('Customers','\u2026',`<button type="button" class="btn primary" data-act="new-customer">${ico('plus')}Add customer</button>`)+`<div class="tools"><div class="search">${ico('search')}<input class="input" type="search" placeholder="Search name or phone" data-live="customers" aria-label="Search customers" maxlength="100" value="${esc(S.cf.q)}"></div></div><div id="clist">${skel(5)}</div>`);
  refreshCustomers()};
LIVE.customers=v=>{S.cf.q=v;refreshCustomers()};
const phoneShow=p=>{p=String(p||'').replace(/\D/g,'');if(p.startsWith('234'))return '+'+p;if(p.startsWith('0'))return '+234'+p.slice(1);return p};
async function refreshCustomers(){
  const n=S.nav;if(!$('#clist'))return;
  try{
    const d=await api('/api/customers?limit=500&search='+encodeURIComponent(S.cf.q));if(n!==S.nav||!$('#clist'))return;
    S.map.customers=new Map(d.items.map(x=>[x.id,x]));const sub=$('.phead p');if(sub)sub.textContent=`${d.items.length} customer${d.items.length===1?'':'s'}`;
    $('#clist').innerHTML=d.items.length?`<section class="panel"><div class="tbl" style="--cols:minmax(0,2fr) 90px 150px 150px;--cols-md:minmax(0,2fr) 140px 140px"><div class="tr th"><div>Customer</div><div class="hide-md">Orders</div><div>Total spent</div><div>Owes you</div></div>${d.items.map(x=>`<div class="tr" data-act="edit-customer" data-id="${esc(x.id)}" role="button" tabindex="0" aria-label="Edit ${esc(x.full_name)}"><div class="cell-main"><span class="thumb">${initial(x.full_name)}</span><div><b>${esc(x.full_name)}</b><small>${esc(phoneShow(x.phone))}</small></div></div><div class="hide-md num" data-label="Orders">${x.total_orders}</div><div class="num" data-label="Total spent">${money(x.total_spent)}</div><div class="num" data-label="Owes you">${x.outstanding_debt>0?`<b>${money(x.outstanding_debt)}</b>`:'<span class="muted">\u2014</span>'}</div></div>`).join('')}</div></section>`
      :`<section class="panel">${S.cf.q?emptyBox('search','No customers match that search','Check the spelling or try a phone number.'):emptyBox('customers','No customers yet','Save your customers so every order and debt has a name next to it.',`<button type="button" class="btn primary" data-act="new-customer">${ico('plus')}Add your first customer</button>`)}</section>`
  }catch(e){if(n===S.nav)$('#clist').innerHTML=alertBox(e.message)}}
function openCustomer(id){
  const x=id&&S.map.customers?S.map.customers.get(id):null;
  const body=`<form id="f-customer" data-form="customer" data-id="${esc(id||'')}"><div class="ferr"></div><div class="field"><label for="c-name">Full name</label><input class="input" id="c-name" name="full_name" required maxlength="180" value="${esc(x?x.full_name:'')}" autocomplete="off"></div><div class="field"><label for="c-phone">Phone</label><input class="input" id="c-phone" name="phone" required inputmode="tel" maxlength="20" pattern="0[789][01][0-9]{8}" title="11-digit Nigerian number, like 08031234567" data-ngphone value="${esc(x?phoneLocal(x.phone):'')}" placeholder="08031234567" autocomplete="off"><span class="hint">Used for WhatsApp reminders and receipts.</span></div><div class="cols2"><div class="field"><label for="c-email">Email <span class="muted">(optional)</span></label><input class="input" id="c-email" type="email" name="email" maxlength="200" value="${esc(x?x.email:'')}"></div><div class="field"><label for="c-addr">Address <span class="muted">(optional)</span></label><input class="input" id="c-addr" name="address" maxlength="500" value="${esc(x?x.address:'')}"></div></div><div class="field"><label for="c-notes">Notes <span class="muted">(optional)</span></label><textarea class="textarea" id="c-notes" name="notes" maxlength="2000">${esc(x?x.notes:'')}</textarea></div></form>${x?`<div class="sect">Records</div><div class="phead-a"><button type="button" class="btn" data-act="cust-statement" data-id="${esc(id)}">${ico('pdf')}Statement PDF${proTag()}</button>${sendBtn(stmtAttrs(x),'Send statement')}<button type="button" class="btn" data-act="cust-history" data-id="${esc(id)}">${ico('history')}Edit history</button></div>`:''}`;
  drawer({title:x?'Edit customer':'Add customer',body,foot:`${x?`<button type="button" class="btn danger" data-act="del-customer" data-id="${esc(id)}">${ico('trash')}Delete</button>`:'<span></span>'}<div class="grow"><button type="button" class="btn" data-act="close-layer">Cancel</button><button class="btn primary" type="submit" form="f-customer">${x?'Save changes':'Add customer'}</button></div>`})}
FORMS.customer=async f=>{
  const id=f.dataset.id;const b=Object.fromEntries(new FormData(f));const btn=$('button[type=submit][form='+f.id+']');const label=btn?btn.textContent:'';busy(btn,true,'Saving\u2026');
  try{await api('/api/customers'+(id?'/'+id:''),{method:id?'PUT':'POST',body:b});closeLayers();toast(id?'Customer saved.':'Customer added.');if(S.route.view==='customers')refreshCustomers()}
  catch(e){formErr(f,e.message)}finally{busy(btn,false,label)}};
ACT['new-customer']=()=>openCustomer(null);
ACT['edit-customer']=el=>openCustomer(el.dataset.id);
ACT['del-customer']=async el=>{
  const id=el.dataset.id;const x=S.map.customers&&S.map.customers.get(id);
  if(!await confirmBox({title:'Delete this customer?',text:`${x?x.full_name:'This customer'} will be removed. Their past orders stay, but show as walk-in customers.`,ok:'Delete customer',danger:true}))return;
  try{await api('/api/customers/'+id,{method:'DELETE',body:{}});closeLayers();toast('Customer deleted.');if(S.route.view==='customers')refreshCustomers()}catch(e){toast(e.message,true)}};

/* =========================== ORDERS =========================== */
const STATUS_OPTS=[{v:'pending',l:'Pending'},{v:'confirmed',l:'Confirmed'},{v:'processing',l:'Processing'},{v:'ready',l:'Ready'},{v:'completed',l:'Completed',h:'Deducts stock'},{v:'cancelled',l:'Cancelled'}];
const PAY_OPTS=['Bank Transfer','Cash','POS','Other'].map(v=>({v,l:v}));
LOAD.orders=async r=>{
  if(r.id)return loadOrderDetail(r.id);
  if(!S.back)S.of={q:'',status:r.q.status||''};
  setPage(pageHead('Orders','\u2026',`<button type="button" class="btn primary" data-act="new-order">${ico('plus')}New order</button>`)
    +`<div class="tools"><div class="search">${ico('search')}<input class="input" type="search" placeholder="Search order number or customer" data-live="orders" aria-label="Search orders" maxlength="100" value="${esc(S.of.q)}"></div>${dd({sm:true,value:S.of.status,label:'Filter by status',options:[{v:'',l:'All statuses'}].concat(STATUS_OPTS.map(o=>({v:o.v,l:o.l}))),onChange:v=>{S.of.status=v;refreshOrders()}})}</div><div id="olist">${skel(5)}</div>`);
  refreshOrders()};
LIVE.orders=v=>{S.of.q=v;refreshOrders()};
async function refreshOrders(){
  const n=S.nav;if(!$('#olist'))return;
  try{
    const d=await api('/api/orders?search='+encodeURIComponent(S.of.q)+(S.of.status?'&status='+S.of.status:''));if(n!==S.nav||!$('#olist'))return;
    const filtered=!!(S.of.q||S.of.status);const sub=$('.phead p');if(sub)sub.textContent=`${d.items.length} order${d.items.length===1?'':'s'}`;
    $('#olist').innerHTML=d.items.length?`<section class="panel"><div class="tbl" style="--cols:minmax(0,2fr) 140px 140px 130px;--cols-md:minmax(0,2fr) 130px 120px"><div class="tr th"><div>Order</div><div>Total</div><div class="hide-md">Balance</div><div>Status</div></div>${d.items.map(x=>`<div class="tr" data-act="open-order" data-id="${esc(x.id)}" role="button" tabindex="0" aria-label="Open order ${esc(x.order_number)}"><div class="cell-main"><div><b>${esc(x.order_number)}</b><small>${esc(x.customer?x.customer.full_name:'Walk-in customer')} \u00b7 ${fmtDate(x.order_date)}</small></div></div><div class="num" data-label="Total">${money(x.total)}</div><div class="hide-md num" data-label="Balance">${x.balance>0?`<b>${money(x.balance)}</b>`:'<span class="muted">Paid</span>'}</div><div data-label="Status">${pill(x.status)}</div></div>`).join('')}</div></section>`
      :`<section class="panel">${filtered?emptyBox('search','No orders match','Try a different search or status.'):emptyBox('orders','No orders yet','Record your first sale to start tracking payments and stock.',`<button type="button" class="btn primary" data-act="new-order">${ico('plus')}Create an order</button>`)}</section>`
  }catch(e){if(n===S.nav)$('#olist').innerHTML=alertBox(e.message)}}
ACT['open-order']=el=>go('orders/'+el.dataset.id);
ACT['new-order']=()=>openOrder(null);
ACT['edit-order']=()=>{if(S.map.order)openOrder(S.map.order)};
CALC.order=f=>{
  let sub=0;
  $$('[data-line]',f).forEach(l=>{const pid=$('input[name=product_id]',l).value;const q=Math.max(0,parseInt($('input[name=quantity]',l).value||'0',10)||0);const p=S.orderProds.get(pid);const t=p?p.selling_price*q:0;sub+=t;$('[data-lt]',l).textContent=p?money(t):'\u2014'});
  const disc=Math.max(0,parseFloat(f.elements.discount.value)||0);const total=Math.max(0,sub-disc);
  const paid=f.dataset.paid!==undefined&&f.dataset.paid!==''?parseFloat(f.dataset.paid)||0:(parseFloat(f.elements.initial_payment&&f.elements.initial_payment.value)||0);
  const set=(k,v)=>{const e=$(`[data-sum=${k}]`,f);if(e)e.textContent=v};
  set('sub',money(sub));set('disc','\u2212 '+money(disc));set('total',money(total));set('paid',money(paid));set('bal',money(Math.max(0,total-paid)));
  const w=$('[data-warn]',f);if(w)w.innerHTML=disc>sub?alertBox('The discount is more than the subtotal.','warn'):paid>total&&total>0?alertBox('The payment is more than the order total.','warn'):''};
async function openOrder(existing){
  let pd2,cd;
  try{[pd2,cd]=await Promise.all([api('/api/products?active=1&limit=500'),api('/api/customers?limit=500')])}catch(e){toast(e.message,true);return}
  if(!pd2.items.length){toast('Add a product first, then create the order.',true);return}
  S.orderProds=new Map(pd2.items.map(p=>[p.id,p]));
  const prodOpts=pd2.items.map(p=>({v:p.id,l:p.name,h:`${money(p.selling_price,true)} \u00b7 ${p.stock_quantity} left`}));
  const custOpts=[{v:'',l:'Walk-in customer'}].concat(cd.items.map(c=>({v:c.id,l:c.full_name,h:phoneShow(c.phone)})));
  S.lineHtml=(it)=>`<div class="line" data-line>${dd({name:'product_id',value:it.product_id||'',placeholder:'Choose a product',options:prodOpts,label:'Product',search:true})}<input class="input" type="number" name="quantity" min="1" step="1" inputmode="numeric" value="${it.quantity||1}" aria-label="Quantity" required><div class="line-t num" data-lt>\u2014</div><button type="button" class="btn danger icon" data-act="rm-line" aria-label="Remove this line">${ico('x')}</button></div>`;
  const e=existing;const lines=(e&&e.items&&e.items.length?e.items:[{}]);
  const body=`<form id="f-order" data-form="order" data-id="${esc(e?e.id:'')}" data-calc="order"${e?` data-paid="${e.amount_paid}"`:''}><div class="ferr"></div>
<div class="cols2"><div class="field"><label>Customer</label>${dd({name:'customer_id',value:e&&e.customer_id?e.customer_id:'',options:custOpts,label:'Customer',search:true})}</div><div class="field"><label for="o-date">Order date</label><input class="input" id="o-date" type="date" name="order_date" required value="${esc(e&&e.order_date?e.order_date.slice(0,10):todayLocal())}"></div></div>
<div class="sect">Products</div><div id="lines">${lines.map(S.lineHtml).join('')}</div><button type="button" class="btn sm" data-act="add-line">${ico('plus')}Add another product</button>
<div class="sect">Payment</div>
<div class="cols2"><div class="field"><label for="o-disc">Discount</label><div class="ig"><span>\u20a6</span><input class="input" id="o-disc" name="discount" type="number" step="0.01" min="0" inputmode="decimal" value="${e?e.discount:0}"></div></div>${e?`<div class="field"><label>Already paid</label><div class="ig"><span>\u20a6</span><input class="input" type="text" value="${e.amount_paid}" disabled aria-label="Already paid"></div><span class="hint">Record more payments from the order page.</span></div>`:`<div class="field"><label for="o-pay">Paid now <span class="muted">(optional)</span></label><div class="ig"><span>\u20a6</span><input class="input" id="o-pay" name="initial_payment" type="number" step="0.01" min="0" inputmode="decimal" value=""></div></div>`}</div>
<div class="cols2"><div class="field"><label>Payment method</label>${dd({name:'payment_method',value:e?e.payment_method:'Bank Transfer',options:PAY_OPTS,label:'Payment method'})}</div><div class="field"><label for="o-due">Debt due date <span class="muted">(optional)</span></label><input class="input" id="o-due" type="date" name="due_date" value="${esc(e&&e.debt&&e.debt.due_date?e.debt.due_date:'')}"></div></div>
<div class="sum"><div class="kv"><span>Subtotal</span><span class="num" data-sum="sub">\u2014</span></div><div class="kv"><span>Discount</span><span class="num" data-sum="disc">\u2014</span></div><div class="kv big"><span>Total</span><span class="num" data-sum="total">\u2014</span></div><div class="kv"><span>Paid</span><span class="num" data-sum="paid">\u2014</span></div><div class="kv"><span>Balance</span><span class="num" data-sum="bal">\u2014</span></div></div><div data-warn></div>
<div class="sect">Status</div><div class="field"><label>Order status</label>${dd({name:'status',value:e?e.status:'pending',options:STATUS_OPTS,label:'Order status'})}<span class="hint">Stock is deducted, and sales and profit are counted, when an order is marked Completed.</span></div>
<div class="field"><label for="o-notes">Notes <span class="muted">(optional)</span></label><textarea class="textarea" id="o-notes" name="notes" maxlength="2000">${esc(e?e.notes:'')}</textarea></div></form>`;
  const w=drawer({title:e?`Edit ${e.order_number}`:'New order',wide:true,body,foot:`${e?`<button type="button" class="btn danger" data-act="del-order" data-id="${esc(e.id)}">${ico('trash')}Delete</button>`:'<span></span>'}<div class="grow"><button type="button" class="btn" data-act="close-layer">Cancel</button><button class="btn primary" type="submit" form="f-order">${e?'Save changes':'Create order'}</button></div>`});
  CALC.order($('form',w))}
ACT['add-line']=el=>{const f=el.closest('form');$('#lines',f).insertAdjacentHTML('beforeend',S.lineHtml({}));CALC.order(f)};
ACT['rm-line']=el=>{const f=el.closest('form');if($$('[data-line]',f).length<2){toast('An order needs at least one product.',true);return}el.closest('[data-line]').remove();CALC.order(f)};
FORMS.order=async f=>{
  const id=f.dataset.id;
  const items=$$('[data-line]',f).map(l=>({product_id:$('input[name=product_id]',l).value,quantity:parseInt($('input[name=quantity]',l).value,10)||0}));
  if(items.some(i=>!i.product_id))return formErr(f,'Choose a product on every line.');
  if(items.some(i=>i.quantity<1))return formErr(f,'Every quantity must be at least 1.');
  if(new Set(items.map(i=>i.product_id)).size!==items.length)return formErr(f,'The same product is on two lines. Combine them into one.');
  const g=n=>f.elements[n]?f.elements[n].value:'';
  const b={customer_id:g('customer_id')||null,order_date:g('order_date'),due_date:g('due_date')||null,discount:g('discount')||'0',payment_method:g('payment_method'),status:g('status'),notes:g('notes'),items};
  if(!id)b.initial_payment=g('initial_payment')||'0';
  const btn=$('button[type=submit][form=f-order]');const label=btn?btn.textContent:'';busy(btn,true,'Saving\u2026');
  try{const d=await api('/api/orders'+(id?'/'+id:''),{method:id?'PUT':'POST',body:b});closeLayers();toast(id?'Order saved.':'Order created.');go('orders/'+d.order.id)}
  catch(err){formErr(f,err.message)}finally{busy(btn,false,label)}};
async function loadOrderDetail(id){
  const n=S.nav;setPage(skel(5));
  try{
    const d=await api('/api/orders/'+id);if(n!==S.nav)return;const x=d.order;S.map.order=x;
    S.map.payments=new Map((x.payments||[]).map(p=>[p.id,Object.assign({order_id:x.id},p)]));
    const locked=x.status==='cancelled';
    const debt=x.debt&&x.balance>0&&!locked?{id:x.debt.id,order_id:x.id,order_number:x.order_number,order_date:x.order_date,customer_name:x.customer?x.customer.full_name:'',original_amount:x.total,amount_paid:x.amount_paid,remaining_balance:x.balance,due_date:x.debt.due_date||''}:null;
    S.map.debts=new Map(debt?[[debt.id,debt]]:[]);
    const adj=Math.round((Number(x.adjustment)||0)*100)/100;
    const tok=x.receipt?esc(x.receipt.public_token):'';
    const head=pageHead(x.order_number,`${x.customer?x.customer.full_name:'Walk-in customer'} · ${fmtDate(x.order_date)}`,
      `${pill(x.status)}<button type="button" class="btn" data-act="edit-order">${ico('edit')}Edit</button>${x.receipt?`<a class="btn" href="${U('/receipt/'+tok)}" target="_blank" rel="noopener noreferrer">${ico('receipts')}Receipt</a><button type="button" class="btn" data-act="pdf-menu" data-token="${tok}" aria-haspopup="menu" aria-expanded="false">${ico('pdf')}PDF${proTag()}</button>${sendBtn(rcptAttrs({num:x.order_number,name:x.customer?x.customer.full_name:'',phone:x.customer?x.customer.phone:'',email:x.customer?x.customer.email:'',total:x.total,bal:x.balance,token:x.receipt.public_token}),'Send','primary')}`:''}<button type="button" class="btn ghost" data-act="order-history" data-id="${esc(x.id)}" title="Every change made to this order and its payments">${ico('history')}History</button>`);
    const totals=`<div class="panel-b"><div class="kv"><span>Subtotal</span><span class="num">${money(x.subtotal)}</span></div><div class="kv"><span>Discount</span><span class="num">− ${money(x.discount)}</span></div>${adj?`<div class="kv"><span>Correction <button type="button" class="link plain" data-act="order-history" data-id="${esc(x.id)}">why?</button></span><span class="num">${adj<0?'− ':'+ '}${money(Math.abs(adj))}</span></div>`:''}<div class="kv big"><span>Total</span><span class="num">${money(x.total)}</span></div><div class="kv"><span>Paid</span><span class="num">${money(x.amount_paid)}</span></div><div class="kv"><span>Balance</span><span class="num"><b>${money(x.balance)}</b></span></div><div class="kv"><span>Estimated profit</span><span class="num">${money(x.estimated_gross_profit)}</span></div></div>`;
    const pays=x.payments.length?`<div class="panel-b">${x.payments.map(p=>`<div class="kv"><span>${fmtDate(p.paid_at)}<br><small class="muted">${esc(p.payment_method)}${p.note?' · '+esc(p.note):''}</small></span><span class="payr"><b class="num">${money(p.amount)}</b>${locked?'':`<button type="button" class="btn sm ghost icon" data-act="edit-payment" data-id="${esc(p.id)}" aria-label="Correct this payment of ${esc(money(p.amount))}" title="Correct or void this payment">${ico('edit')}</button>`}</span></div>`).join('')}</div>`:emptyBox('debts','No payment yet','Payments you record show up here.');
    const owed=debt?`<div class="panel-b"><div class="kv"><span>${debt.due_date?'Payment due':'No due date'}</span><span>${debt.due_date?fmtDate(debt.due_date):''}</span></div><div class="phead-a" style="margin-top:6px"><button type="button" class="btn sm" data-act="edit-debt" data-id="${esc(debt.id)}">${ico('edit')}Correct amount owed</button></div></div>`:'';
    const lockNote=locked?`<div class="panel-b"><p class="muted" style="margin:0">This order is cancelled, so its payments and debt are locked.</p></div>`:'';
    setPage(head
    +`<div class="cols"><section class="panel"><div class="panel-h"><h2>Items</h2></div><div class="tbl" style="--cols:minmax(0,1fr) 60px 120px 130px;--cols-md:minmax(0,1fr) 50px 110px"><div class="tr th"><div>Product</div><div>Qty</div><div class="hide-md">Price</div><div class="right">Total</div></div>${x.items.map(i=>`<div class="tr"><div><b>${esc(i.product_name)}</b></div><div class="num" data-label="Quantity">${i.quantity}</div><div class="hide-md num" data-label="Price">${money(i.unit_price)}</div><div class="right num" data-label="Total">${money(i.line_total)}</div></div>`).join('')}</div>${totals}</section>
<section class="panel"><div class="panel-h"><h2>Payments</h2>${x.balance>0&&!locked?`<button type="button" class="btn primary sm" data-act="pay" data-id="${esc(x.id)}" data-bal="${x.balance}">${ico('plus')}Record payment</button>`:''}</div>${pays}${owed}${lockNote}${x.notes?`<div class="panel-b"><div class="lbl">Notes</div><p class="muted" style="margin:6px 0 0">${esc(x.notes)}</p></div>`:''}</section></div>`)
  }catch(e){if(n===S.nav)setPage(alertBox(e.message))}}
ACT.pay=el=>{
  const bal=parseFloat(el.dataset.bal)||0;
  dialog(`<div class="row-b"><h2>Record payment</h2><button type="button" class="btn ghost icon" data-act="close-layer" aria-label="Close">${ico('x')}</button></div><form data-form="payment" data-id="${esc(el.dataset.id)}"><div class="ferr"></div><div class="alert info">${ico('shield')}<span>Balance still owed: <b>${money(bal)}</b></span></div><div class="field"><label for="pay-amt">Amount</label><div class="ig"><span>\u20a6</span><input class="input" id="pay-amt" name="amount" type="number" step="0.01" min="0.01" max="${bal}" inputmode="decimal" required value="${bal}"></div></div><div class="field"><label>Payment method</label>${dd({name:'payment_method',value:'Bank Transfer',options:PAY_OPTS,label:'Payment method'})}</div><div class="field"><label for="pay-note">Note <span class="muted">(optional)</span></label><input class="input" id="pay-note" name="note" maxlength="500"></div><div class="dlg-act"><button type="button" class="btn" data-act="close-layer">Cancel</button><button class="btn primary" type="submit">Record payment</button></div></form>`,'Record payment')};
FORMS.payment=async f=>{
  const id=f.dataset.id;const b=Object.fromEntries(new FormData(f));const btn=$('button[type=submit]',f);busy(btn,true);
  try{await api('/api/orders/'+id+'/payments',{method:'POST',body:b});closeLayers();toast('Payment recorded.');loadOrderDetail(id)}
  catch(e){formErr(f,e.message)}finally{busy(btn,false)}};

/* =========================== DEBTS / RECEIPTS =========================== */
LOAD.receipts=async()=>{
  const n=S.nav;setPage(pageHead('Receipts','A shareable receipt for every order.')+skel(4));
  try{
    const d=await api('/api/receipts');if(n!==S.nav)return;
    setPage(pageHead('Receipts',`${d.items.length} receipt${d.items.length===1?'':'s'}`)+`<section class="panel">${d.items.length?`<div class="tbl" style="--cols:minmax(0,1.7fr) 130px 130px 130px 290px;--cols-md:minmax(0,1.7fr) 120px 290px"><div class="tr th"><div>Order</div><div>Total</div><div class="hide-md">Paid</div><div class="hide-md">Balance</div><div></div></div>${d.items.map(x=>`<div class="tr"><div class="cell-main"><div><b>${esc(x.order_number)}</b><small>${esc(x.customer_name||'Walk-in customer')} \u00b7 ${fmtDate(x.order_date)}</small></div></div><div class="num" data-label="Total">${money(x.total)}</div><div class="hide-md num" data-label="Paid">${money(x.amount_paid)}</div><div class="hide-md num" data-label="Balance">${money(x.balance)}</div><div class="phead-a nowrap"><a class="btn sm" href="${esc(U('/receipt/'+x.public_token))}" target="_blank" rel="noopener noreferrer">Open${ico('ext')}</a><button type="button" class="btn sm" data-act="pdf-menu" data-token="${esc(x.public_token)}" aria-haspopup="menu" aria-expanded="false">${ico('pdf')}PDF${proTag()}</button>${sendBtn(rcptAttrs({num:x.order_number,name:x.customer_name,phone:x.customer_phone,email:x.customer_email||'',total:x.total,bal:x.balance,token:x.public_token}),'Send')}</div></div>`).join('')}</div>`:emptyBox('receipts','No receipts yet','A receipt is created automatically with each order.')}</section>`)
  }catch(e){if(n===S.nav)setPage(alertBox(e.message))}};

/* =========================== STOREFRONT =========================== */
LOAD.storefront=async()=>{
  const n=S.nav;setPage(pageHead('Storefront','A public page where customers can browse and order.')+skel(2));
  try{
    const d=await api('/api/business');if(n!==S.nav)return;const b=d.business;S.biz=b;const url=U('/store/'+b.slug);
    const msg=encodeURIComponent('Shop with us online: '+url);
    setPage(pageHead('Storefront','A public page where customers can browse and order.',`<a class="btn primary" href="${esc(url)}" target="_blank" rel="noopener noreferrer">${ico('ext')}Open storefront</a>`)
    +(b.storefront_enabled?'':`<div class="alert warn">${ico('alert')}<span>Your storefront is switched off, so this link shows \u201cStore not found\u201d. Turn it on in Settings.</span></div>`)
    +`<section class="panel"><div class="panel-b"><div class="field"><label for="s-url">Your store link</label><div class="phead-a" style="flex-wrap:nowrap"><input class="input" id="s-url" readonly value="${esc(url)}"><button type="button" class="btn" data-act="copy" data-text="${esc(url)}">${ico('copy')}Copy</button></div></div><div class="phead-a"><a class="btn" href="https://wa.me/?text=${msg}" target="_blank" rel="noopener noreferrer">${ico('chat')}Share on WhatsApp</a></div></div></section>
<div class="alert info" style="margin-top:18px">${ico('shield')}<span>Visitors see only active products: name, description, photo, price, category and whether it is available. Cost prices and everything else stay private.</span></div>`)
  }catch(e){if(n===S.nav)setPage(alertBox(e.message))}};

/* =========================== REPORTS =========================== */
const RANGES=[{v:'7',l:'Last 7 days'},{v:'30',l:'Last 30 days'},{v:'month',l:'This month'},{v:'last',l:'Last month'},{v:'custom',l:'Custom dates'}];
const ymd=d=>d.toLocaleDateString('en-CA');
function rangeDates(v){const t=new Date();if(v==='7'||v==='30'){const s=new Date(t);s.setDate(t.getDate()-(+v-1));return[ymd(s),ymd(t)]}if(v==='month')return[ymd(new Date(t.getFullYear(),t.getMonth(),1)),ymd(t)];if(v==='last')return[ymd(new Date(t.getFullYear(),t.getMonth()-1,1)),ymd(new Date(t.getFullYear(),t.getMonth(),0))];return null}
LOAD.reports=()=>{
  const [s,e]=rangeDates('30');
  const cfg={sm:true,value:'30',label:'Date range',options:RANGES,onChange:v=>{const r=rangeDates(v);if(r){$('#rstart').value=r[0];$('#rend').value=r[1];runReport()}}};
  setPage(pageHead('Reports','Sales performance without the accounting clutter.',`<button type="button" class="btn" data-act="dl-report" data-fmt="csv" title="Download as a spreadsheet (CSV, opens in Excel or Google Sheets)">${ico('download')}Spreadsheet${proTag()}</button><button type="button" class="btn primary" data-act="dl-report" data-fmt="pdf">${ico('pdf')}Download PDF${proTag()}</button>`)+`<div class="tools">${dd(cfg)}<input class="input" id="rstart" type="date" value="${s}" aria-label="From" style="max-width:170px" data-live="rdates"><input class="input" id="rend" type="date" value="${e}" aria-label="To" style="max-width:170px" data-live="rdates"></div><div id="rbody">${skel(3)}</div>`);
  S.rcfg=cfg;runReport()};
LIVE.rdates=()=>{if(S.rcfg)ddSet(S.rcfg.id,'custom',true);runReport()};
async function runReport(){
  const n=S.nav;const box=$('#rbody');if(!box)return;
  try{
    const d=await api('/api/reports?start='+encodeURIComponent($('#rstart').value)+'&end='+encodeURIComponent($('#rend').value));if(n!==S.nav||!$('#rbody'))return;
    const mx=Math.max(1,...d.best_sellers.map(x=>x.sales));const mc=Math.max(1,...d.top_customers.map(x=>x.spent));
    box.innerHTML=`<div class="kpis six"><div class="kpi"><div class="k">Sales</div><div class="v num">${money(d.total_sales,true)}</div></div><div class="kpi"><div class="k">Orders</div><div class="v num">${d.order_count}</div></div><div class="kpi"><div class="k">Average order</div><div class="v num">${money(d.average_order_value,true)}</div></div><div class="kpi"><div class="k">Estimated profit</div><div class="v num">${money(d.estimated_gross_profit,true)}</div></div><div class="kpi"><div class="k">Expenses</div><div class="v num"${d.expenses_total>0?' style="color:var(--bad)"':''}>${money(d.expenses_total,true)}</div></div><div class="kpi"><div class="k">Net profit</div><div class="v num" style="color:var(--${d.net_profit<0?'bad':'ok'})">${money(d.net_profit,true)}</div></div></div>
<div class="cols even"><section class="panel"><div class="panel-h"><h2>Best-selling products</h2></div><div class="panel-b">${d.best_sellers.length?`<div class="bars">${d.best_sellers.map(x=>`<div class="hb"><div class="t"><b>${esc(x.name)}</b><span class="num">${money(x.sales,true)}</span></div><div class="tr2"><i style="--w:${(x.sales/mx*100).toFixed(1)}%"></i></div><small class="muted">${x.quantity} sold</small></div>`).join('')}</div>`:emptyBox('reports','No sales in these dates','Completed orders appear here.')}</div></section>
<section class="panel"><div class="panel-h"><h2>Top customers</h2></div><div class="panel-b">${d.top_customers.length?`<div class="bars">${d.top_customers.map(x=>`<div class="hb"><div class="t"><b>${esc(x.name)}</b><span class="num">${money(x.spent,true)}</span></div><div class="tr2"><i style="--w:${(x.spent/mc*100).toFixed(1)}%"></i></div><small class="muted">${x.orders} order${x.orders===1?'':'s'}</small></div>`).join('')}</div>`:emptyBox('customers','No customer sales yet','Assign customers to orders to build this list.')}</div></section></div>`
  }catch(e){if(n===S.nav&&$('#rbody'))$('#rbody').innerHTML=alertBox(e.message)}}

ACT['dl-report']=el=>{
  if(!isPro()){showUpgrade('report_export');return}
  const s=$('#rstart')&&$('#rstart').value,e=$('#rend')&&$('#rend').value;
  if(!s||!e){toast('Choose both dates first.',true);return}
  const fmt=el.dataset.fmt;
  download(`/api/reports/export?format=${fmt}&start=${encodeURIComponent(s)}&end=${encodeURIComponent(e)}`,`ojaloom-sales.${fmt}`,el,fmt==='pdf'?'PDF report downloaded.':'Spreadsheet downloaded. It opens in Excel or Google Sheets.')};

/* =========================== SETTINGS =========================== */
LOAD.settings=async()=>{
  const n=S.nav;setPage(pageHead('Settings','Your business, your categories and your account.')+skel(4));
  try{
    const [bd]=await Promise.all([api('/api/business'),loadCats(true).catch(()=>{})]);if(n!==S.nav)return;
    const b=bd.business;S.biz=b;
    const bizOpts=BOOT.categories.map(c=>({v:c,l:c}));if(b.category&&!BOOT.categories.includes(b.category))bizOpts.unshift({v:b.category,l:b.category});
    setPage(pageHead('Settings','Your business, your categories and your account.')
    +`<div class="cols even"><div><section class="panel"><div class="panel-h"><h2>Business profile</h2></div><div class="panel-b"><form id="f-biz" data-form="business"><div class="ferr"></div>
<div class="field"><label for="b-name">Business name</label><input class="input" id="b-name" name="name" required maxlength="160" value="${esc(b.name)}"></div>
<div class="cols2"><div class="field"><label for="b-owner">Owner name</label><input class="input" id="b-owner" name="owner_name" maxlength="120" value="${esc(b.owner_name)}"></div><div class="field"><label for="b-phone">Phone</label><input class="input" id="b-phone" name="phone" inputmode="tel" required maxlength="20" pattern="0[789][01][0-9]{8}" title="11-digit Nigerian number, like 08031234567" data-ngphone value="${esc(phoneLocal(b.phone))}" placeholder="08031234567"></div></div>
<div class="cols2"><div class="field"><label for="b-email">Email</label><input class="input" id="b-email" type="email" name="email" maxlength="200" value="${esc(b.email)}"></div><div class="field"><label>Business type</label>${dd({name:'category',value:b.category,options:bizOpts,placeholder:'Choose a type',label:'Business type',search:true})}</div></div>
<div class="field"><label for="b-desc">About your business</label><textarea class="textarea" id="b-desc" name="description" maxlength="2500">${esc(b.description)}</textarea></div>
<div class="field"><label for="b-addr">Address</label><input class="input" id="b-addr" name="address" maxlength="500" value="${esc(b.address)}"></div>
${imageField(b.has_logo?b.logo_url:'','logo')}
<div class="field"><label for="b-rcpt">Receipt thank-you message</label><input class="input" id="b-rcpt" name="receipt_message" maxlength="500" value="${esc(b.receipt_message)}"></div>
<div class="cols2"><div class="field"><label>Storefront</label>${dd({name:'storefront_enabled',value:b.storefront_enabled?'1':'0',label:'Storefront',options:[{v:'1',l:'On',h:'Public'},{v:'0',l:'Off',h:'Hidden'}]})}</div><div class="field"><label>Selling below zero stock</label>${dd({name:'allow_negative_inventory',value:b.allow_negative_inventory?'1':'0',label:'Negative stock',options:[{v:'0',l:'Block it'},{v:'1',l:'Allow it'}]})}</div></div>
<button class="btn primary" type="submit">Save business</button></form></div></section></div>
<div><section class="panel"><div class="panel-h"><h2>Product categories</h2></div><div class="panel-b" id="catpanel">${catPanel()}</div></section>
<section class="panel" style="margin-top:18px"><div class="panel-h"><h2>Account and security</h2></div><div class="panel-b"><div class="kv"><span>Signed in as</span><b>${esc(S.me.email)}</b></div>${SUPPORT_WA?`<div class="kv"><span>Customer support</span><span><a class="link plain" href="${esc(supportLink())}" target="_blank" rel="noopener noreferrer">Chat on WhatsApp</a> \u00b7 ${esc(supportNumber())}</span></div>`:''}<div class="kv"><span>Plan</span><b>${esc(planLabel(b))}</b></div>${b.access&&b.access.ends_at?`<div class="kv"><span>${b.access.state==='pro'?'Pro runs until':'Trial ends'}</span><b>${fmtDate(b.access.ends_at)}</b></div>`:`<div class="kv"><span>Trial ended</span><b>${fmtDate(b.trial_end)}</b></div>`}<div class="phead-a" style="margin:6px 0 4px"><button type="button" class="btn sm" data-act="nav" data-to="billing">${ico('billing')}Manage plan</button><button type="button" class="btn sm" data-act="nav" data-to="history">${ico('history')}Edit history</button></div>
<div class="kv"><span>Your records</span><span><button type="button" class="btn sm" data-act="dl-backup">${ico('download')}Download a backup</button></span></div>
<div class="kv"><span>Terms of Service</span><span><a class="link plain" href="${U('/terms')}" target="_blank" rel="noopener">Read</a> \u00b7 ${S.me.terms_ok?'accepted '+fmtDate(S.me.terms_accepted_at):'not accepted yet'}</span></div>
<div class="sect">Change password</div><form id="f-pw" data-form="password" data-calc="pw"><div class="ferr"></div><div class="field"><label for="pw-cur">Current password</label>${pwField('pw-cur','current_password','current-password')}</div><div class="field"><label for="pw-new">New password</label>${pwField('pw-new','new_password','new-password').replace('<input ','<input data-pwmeter ')}<div class="meter"><i></i></div><div class="meter-t">Use at least ${BOOT.minPassword} characters.</div></div><button class="btn" type="submit">Change password</button></form>
<div class="sect">Sessions</div><p class="muted" style="margin-top:0">Logged in on a shared phone or computer? Sign out everywhere.</p><div class="phead-a"><button type="button" class="btn danger" data-act="logout-all">${ico('shield')}Sign out of all devices</button><button type="button" class="btn" data-act="logout">${ico('logout')}Log out</button></div></div></section></div></div>`)
  }catch(e){if(n===S.nav)setPage(alertBox(e.message))}};
function catPanel(){
  const own=(S.cats||[]).filter(c=>c.kind!=='default');
  return `<p class="muted" style="margin-top:0">These appear first in every category dropdown. Common ones like Fashion &amp; Clothing are always available.</p>${own.length?`<div class="chips">${own.map(c=>`<span class="chip">${esc(c.name)}${c.count?` <small>${c.count}</small>`:''}${c.kind==='custom'?`<button type="button" data-act="del-cat" data-id="${esc(c.id)}" aria-label="Remove ${esc(c.name)}">${ico('x')}</button>`:'<span style="width:6px"></span>'}</span>`).join('')}</div>`:'<p class="hint">You have not added any yet.</p>'}<form data-form="addcat" class="phead-a" style="flex-wrap:nowrap;margin-top:16px"><input class="input" name="name" maxlength="60" placeholder="New category name" aria-label="New category name" required><button class="btn" type="submit">${ico('plus')}Add</button></form>`}
FORMS.addcat=async f=>{
  const name=f.elements.name.value;const btn=$('button[type=submit]',f);busy(btn,true);
  try{await createCategory(name);$('#catpanel').innerHTML=catPanel()}catch(e){toast(e.message,true)}finally{busy(btn,false)}};
ACT['del-cat']=async el=>{
  try{const d=await api('/api/categories/'+el.dataset.id,{method:'DELETE',body:{}});S.cats=d.items;$('#catpanel').innerHTML=catPanel();toast('Category removed.')}catch(e){toast(e.message,true)}};
FORMS.business=async f=>{
  const b=Object.fromEntries(new FormData(f));b.storefront_enabled=b.storefront_enabled==='1';b.allow_negative_inventory=b.allow_negative_inventory==='1';
  const btn=$('button[type=submit]',f);busy(btn,true,'Saving\u2026');
  try{const d=await api('/api/business',{method:'PUT',body:b});S.biz=d.business;toast('Business settings saved.');renderApp();showRoute()}
  catch(e){formErr(f,e.message);busy(btn,false,'Save business')}};
FORMS.password=async f=>{
  const b=Object.fromEntries(new FormData(f));const btn=$('button[type=submit]',f);busy(btn,true);
  try{await api('/api/account/password',{method:'POST',body:b});f.reset();CALC.pw(f);toast('Password changed. Other devices were signed out.')}
  catch(e){formErr(f,e.message)}finally{busy(btn,false)}};
ACT['logout-all']=async()=>{if(await confirmBox({title:'Sign out of all devices?',text:'You will be logged out here too and will need to log in again.',ok:'Sign out everywhere',danger:true}))logout(true)};

/* =========================== REFERRALS =========================== */
LOAD.referrals=async()=>{
  const n=S.nav;setPage(pageHead('Referrals','Invite shop owners you know. You both get free days.')+skel(4));
  try{
    const d=await api('/api/referrals');if(n!==S.nav)return;
    S.biz.trial_end=d.trial_end;S.biz.subscription_status=d.subscription_status;
    try{const bd=await api('/api/business');S.biz=bd.business}catch(x){}
    if(n!==S.nav)return;refreshTrial();
    const r=d.rules,req=r.sales_required,link=appBase()+'?ref='+d.code;
    const text=`I run my shop on Oja Loom. It tracks orders, stock and who owes me. Sign up with my link and get ${r.referred_bonus_days} extra free days: ${link}`;
    const wa='https://wa.me/?text='+encodeURIComponent(text);
    const state=i=>i.status==='joined'?(i.needed?`<span class="pill gold">${i.sales} of ${i.needed} sale${i.needed===1?'':'s'}</span>`:'<span class="pill">Joined</span>'):i.days>0?'<span class="pill ok">Reward earned</span>':'<span class="pill">Joined</span>';
    setPage(pageHead('Referrals','Invite shop owners you know. You both get free days.')
    +`<section class="ref-hero"><h2>Your invite link</h2><p>They get ${r.referred_bonus_days} extra free days when they sign up. You get ${r.referrer_bonus_days} when their shop hits its sales target. You can earn up to ${r.max_rewards} rewards, and each one is tougher to earn than the last.</p><div class="phead-a nowrap"><input class="input" id="r-link" readonly value="${esc(link)}" aria-label="Your invite link"><button type="button" class="btn gold" data-act="copy" data-text="${esc(link)}">${ico('copy')}Copy</button></div><div class="phead-a" style="margin-top:12px"><a class="btn lite" href="${esc(wa)}" target="_blank" rel="noopener noreferrer">${ico('chat')}Share on WhatsApp</a>${navigator.share?`<button type="button" class="btn lite" data-act="share-ref" data-text="${esc(text)}">Share\u2026</button>`:''}</div><small>Your code: <span class="code">${esc(d.code)}</span></small></section>`
    +`<div class="kpis three" style="margin-top:18px"><div class="kpi"><div class="k">Shops joined</div><div class="v num">${d.stats.joined}</div></div><div class="kpi"><div class="k">Rewards earned</div><div class="v num">${d.stats.rewards}</div></div><div class="kpi"><div class="k">Free days earned</div><div class="v num">${d.stats.days_earned}</div></div></div>`
    +(d.referred_by?`<div class="alert info" style="margin-top:18px">${ico('gift')}<span>You joined through <b>${esc(d.referred_by.name)}</b> and got ${d.referred_by.bonus_days} extra free days.</span></div>`:'')
    +`<div class="cols"><section class="panel"><div class="panel-h"><h2>Your referrals</h2></div>${d.items.length?`<div class="tbl" style="--cols:minmax(0,2fr) 200px 100px;--cols-md:minmax(0,2fr) 190px"><div class="tr th"><div>Shop</div><div>Status</div><div class="hide-md right">Reward</div></div>${d.items.map(i=>`<div class="tr"><div class="cell-main"><span class="thumb">${initial(i.name)}</span><div><b>${esc(i.name)}</b><small>Joined ${fmtDate(i.joined_at)}</small></div></div><div data-label="Status">${state(i)}</div><div class="hide-md right num" data-label="Reward">${i.days>0?'+'+i.days+' days':'\u2014'}</div></div>`).join('')}</div>`:emptyBox('gift','No referrals yet','Share your link. When a shop owner you invite makes their first sale, the free days land here.')}</section>
<section class="panel"><div class="panel-h"><h2>How it works</h2></div><div class="panel-b"><ol class="steps"><li class="step"><div><b>Share your link</b><span>Send it to a shop owner by WhatsApp or SMS.</span></div></li><li class="step"><div><b>They sign up</b><span>They start with ${14+r.referred_bonus_days} free days instead of 14.</span></div></li><li class="step"><div><b>They keep selling</b><span>When their orders are marked Completed and they hit the target, you get ${r.referrer_bonus_days} free days. Your 1st reward needs ${req[0]} completed sale${req[0]===1?'':'s'}. Each one after needs more: ${req.slice(1).join(', ')}.</span></div></li></ol><p class="hint" style="margin:18px 0 0">You can earn rewards from up to ${r.max_rewards} shops${d.stats.slots_left<r.max_rewards?` (${d.stats.slots_left} left)`:''}. ${d.stats.slots_left?`Your next reward needs ${d.stats.next_needed} completed sale${d.stats.next_needed===1?'':'s'} from a shop you referred.`:'You have used all your rewards.'} Sign-ups using your own phone number do not count.</p></div></section></div>`)
  }catch(e){if(n===S.nav)setPage(alertBox(e.message))}};
ACT['share-ref']=el=>{if(navigator.share)navigator.share({title:'Oja Loom',text:el.dataset.text}).catch(()=>{})};

/* =========================== PLAN HELPERS + DOWNLOADS =========================== */
const acc=()=>(S.biz&&S.biz.access)||{pro:true,state:'trial',features:{},price:1000};
const isPro=()=>!!acc().pro;
const proTag=()=>isPro()?'':`<span class="protag">${ico('lock')}Pro</span>`;
const upgradeChip=b=>{const a=b&&b.access;if(!a||a.state==='pro')return '';return `<button type="button" class="upg" data-act="nav" data-to="billing">${ico('billing')}<span>${a.state==='free'?'Upgrade to Pro':'See Oja Loom Pro'}</span></button>`};
function showUpgrade(feature,msg){
  const a=acc();const f=(a.features||{})[feature]||{};
  dialog(`<div class="row-b"><h2>${esc(f.name||'Oja Loom Pro')}</h2><button type="button" class="btn ghost icon" data-act="close-layer" aria-label="Close">${ico('x')}</button></div>
<div class="pro-hero">${ico('billing')}<div><b>${money(a.price||1000,true)} a month</b><span>One price for every Pro feature. No contract.</span></div></div>
<p class="muted" style="margin:0 0 6px">${esc(msg||f.pitch||'This is part of Oja Loom Pro.')}</p>${msg&&f.pitch?`<p class="muted" style="margin:0">${esc(f.pitch)}</p>`:''}
<div class="dlg-act"><button type="button" class="btn" data-act="close-layer">Not now</button><button type="button" class="btn primary" data-act="see-pro">See Oja Loom Pro</button></div>`,'Oja Loom Pro')}
ACT['see-pro']=()=>{closeLayers();go('billing')};
async function download(url,fallback,el,okMsg){
  const label=el?el.innerHTML:'';if(el){el.disabled=true;el.textContent='Preparing…'}
  try{
    const res=await fetch(U(url),{credentials:'include'});
    if(!res.ok){let d={};try{d=await res.json()}catch(x){}
      if(res.status===402){showUpgrade(d.upgrade||'pdf_receipt',d.error);return}
      throw new Error(d.error||'Could not prepare the download.')}
    const blob=await res.blob();const cd=res.headers.get('Content-Disposition')||'';const m=/filename="([^"]+)"/.exec(cd);
    const u=URL.createObjectURL(blob);const a=document.createElement('a');a.href=u;a.download=m?m[1]:fallback;document.body.appendChild(a);a.click();a.remove();
    setTimeout(()=>URL.revokeObjectURL(u),6000);if(okMsg)toast(okMsg)
  }catch(err){toast(err.message,true)}finally{if(el){el.disabled=false;el.innerHTML=label}}}
ACT['pdf-menu']=el=>{
  if(!isPro()){showUpgrade('pdf_receipt');return}
  const t=` data-token="${esc(el.dataset.token)}"`;
  if(ddOpenState&&ddOpenState.kind==='menu'){ddClose(true);return}
  popMenu(el,[{icon:'receipts',label:'Receipt (A4)',run:'dl-receipt',attrs:t+' data-kind="receipt"'},{icon:'orders',label:'Invoice (A4)',run:'dl-receipt',attrs:t+' data-kind="invoice"'},{icon:'receipts',label:'Till slip (80 mm)',run:'dl-receipt',attrs:t+' data-kind="thermal"'}],'Download PDF')};
ACT['dl-receipt']=el=>download(`/receipt/${encodeURIComponent(el.dataset.token)}/pdf?kind=${encodeURIComponent(el.dataset.kind||'receipt')}`,'receipt.pdf',null,'PDF downloaded.');
const REASON_FIELD=(opts,id)=>`<div class="field" data-reason><label>Why are you changing it?</label>${dd({name:'reason_pick',value:'',emptyPh:true,placeholder:'Choose a reason',label:'Reason',options:opts.map(v=>({v,l:v}))})}</div><div class="field" data-reason><label for="${id}">More detail <span class="muted">(optional)</span></label><input class="input" id="${id}" name="reason_more" maxlength="300" autocomplete="off"></div>`;
const reasonText=f=>{const g=n=>f.elements[n]?f.elements[n].value.trim():'';return [g('reason_pick'),g('reason_more')].filter(Boolean).join(': ')};
const PAY_REASONS=['I typed the wrong amount','Recorded on the wrong order','Payment bounced or was reversed','Entered twice by mistake','Wrong date or method','Other'];
const DEBT_REASONS=['I typed the wrong amount','Customer paid and I forgot to record it','We agreed a discount','Price or quantity was wrong','Goods were returned','Written off, will not be paid','Other'];

/* =========================== ORDER: EDIT PAYMENTS, DELETE, HISTORY =========================== */
ACT['order-history']=el=>go('history?entity='+encodeURIComponent(el.dataset.id));
ACT['edit-payment']=el=>{
  const p=S.map.payments&&S.map.payments.get(el.dataset.id);if(!p)return;
  drawer({title:'Correct a payment',body:`<form id="f-payedit" data-form="payedit" data-id="${esc(p.id)}" data-oid="${esc(p.order_id)}"><div class="ferr"></div>
<div class="alert info">${ico('shield')}<span>The old values stay in your edit history, with the reason you give.</span></div>
<div class="cols2"><div class="field"><label for="pe-amt">Amount</label><div class="ig"><span>₦</span><input class="input" id="pe-amt" name="amount" type="number" step="0.01" min="0.01" inputmode="decimal" required value="${p.amount}"></div></div><div class="field"><label for="pe-date">Date paid</label><input class="input" id="pe-date" type="date" name="paid_at" value="${esc(String(p.paid_at).slice(0,10))}"></div></div>
<div class="field"><label>Payment method</label>${dd({name:'payment_method',value:p.payment_method,options:PAY_OPTS,label:'Payment method'})}</div>
<div class="field"><label for="pe-note">Note <span class="muted">(optional)</span></label><input class="input" id="pe-note" name="note" maxlength="500" value="${esc(p.note||'')}" autocomplete="off"></div>
${REASON_FIELD(PAY_REASONS,'pe-more')}</form>`,
    foot:`<button type="button" class="btn danger" data-act="void-payment" data-id="${esc(p.id)}">${ico('trash')}Void payment</button><div class="grow"><button type="button" class="btn" data-act="close-layer">Cancel</button><button class="btn primary" type="submit" form="f-payedit">Save correction</button></div>`})};
FORMS.payedit=async f=>{
  const reason=reasonText(f);if(reason.length<3)return formErr(f,'Choose a reason, or write one in the detail box.');
  const b={amount:f.elements.amount.value,paid_at:f.elements.paid_at.value,payment_method:f.elements.payment_method.value,note:f.elements.note.value,reason};
  const btn=$('button[type=submit][form=f-payedit]');const label=btn?btn.textContent:'';busy(btn,true,'Saving…');
  try{await api('/api/payments/'+f.dataset.id,{method:'PUT',body:b});closeLayers();toast('Payment corrected. The change is in your edit history.');loadOrderDetail(f.dataset.oid)}
  catch(e){formErr(f,e.message)}finally{busy(btn,false,label)}};
ACT['void-payment']=async el=>{
  const f=$('#f-payedit');if(!f)return;const reason=reasonText(f);
  if(reason.length<3){formErr(f,'Choose a reason first, then void the payment.');return}
  const p=S.map.payments&&S.map.payments.get(el.dataset.id);
  if(!await confirmBox({title:'Void this payment?',text:`${p?money(p.amount):'This payment'} will be taken off the order and the balance goes back up. It stays in your edit history.`,ok:'Void payment',danger:true}))return;
  try{await api('/api/payments/'+el.dataset.id,{method:'DELETE',body:{reason}});closeLayers();toast('Payment voided. It is kept in your edit history.');loadOrderDetail(f.dataset.oid)}catch(e){toast(e.message,true)}};
ACT['del-order']=async el=>{
  const x=S.map.order;
  if(!await confirmBox({title:'Delete this order?',text:`${x?x.order_number:'This order'} will be removed and its stock put back. An order that has payments cannot be deleted: void the payments first. The deletion is kept in your edit history.`,ok:'Delete order',danger:true}))return;
  try{await api('/api/orders/'+el.dataset.id,{method:'DELETE',body:{}});closeLayers();toast('Order deleted.');go('orders')}catch(e){toast(e.message,true)}};

/* =========================== DEBTS (list + correct amount owed) =========================== */
const debtActions=()=>`<button type="button" class="btn" data-act="dl-debts" data-fmt="csv" title="Open in Excel or Google Sheets">${ico('download')}Spreadsheet${proTag()}</button><button type="button" class="btn primary" data-act="dl-debts" data-fmt="pdf">${ico('pdf')}PDF report${proTag()}</button>`;
LOAD.debts=async r=>{
  const n=S.nav;if(!S.back||!S.df)S.df={filter:r.q.filter||'all',q:''};
  setPage(pageHead('Debts','Money your customers still owe you.',debtActions())+skel(4));
  try{
    const d=await api('/api/debts');if(n!==S.nav)return;
    S.debts=d;S.map.debts=new Map(d.items.map(x=>[x.id,x]));
    const cfg={sm:true,value:S.df.filter,label:'Filter debts',options:[{v:'all',l:'All open debts'},{v:'overdue',l:'Past due date'},{v:'current',l:'Not due yet'}],onChange:v=>{S.df.filter=v;renderDebts()}};
    setPage(pageHead('Debts','Money your customers still owe you.',debtActions())
      +`<div class="kpis"><div class="kpi owed"><div class="k">Total owed to you</div><div class="v num">${money(d.total_outstanding,true)}</div></div><div class="kpi"><div class="k">Past due date</div><div class="v num"${d.overdue_total>0?' style="color:var(--bad)"':''}>${money(d.overdue_total,true)}</div></div><div class="kpi"><div class="k">Customers owing</div><div class="v num">${d.customers_owing}</div></div><div class="kpi"><div class="k">Open debts</div><div class="v num">${d.items.length}</div></div></div>`
      +`<div class="tools" style="margin-top:18px"><div class="search">${ico('search')}<input class="input" type="search" placeholder="Search customer or order number" data-live="debts" aria-label="Search debts" maxlength="100" value="${esc(S.df.q)}"></div>${dd(cfg)}</div><div id="dlist"></div>`);
    renderDebts()
  }catch(e){if(n===S.nav)setPage(alertBox(e.message))}};
LIVE.debts=v=>{S.df.q=v;renderDebts()};
function renderDebts(){
  const box=$('#dlist');if(!box||!S.debts)return;const q=S.df.q.toLowerCase();
  const items=S.debts.items.filter(x=>(S.df.filter==='all'||(S.df.filter==='overdue'?x.status==='overdue':x.status!=='overdue'))&&(!q||String(x.customer_name||'walk-in customer').toLowerCase().includes(q)||String(x.order_number).toLowerCase().includes(q)));
  box.innerHTML=`<section class="panel">${items.length?`<div class="tbl" style="--cols:minmax(0,1.8fr) 150px 130px 170px 210px;--cols-md:minmax(0,1.8fr) 130px 210px"><div class="tr th"><div>Customer</div><div class="hide-md">Paid so far</div><div>Still owed</div><div class="hide-md">Status</div><div></div></div>${items.map(x=>{
    const wa=x.customer_phone?`https://wa.me/${String(x.customer_phone).replace(/\D/g,'')}?text=${encodeURIComponent('Hello '+(x.customer_name||'')+', this is a friendly reminder that your balance for '+x.order_number+' is '+money(x.remaining_balance)+'. Thank you.')}`:'';
    return `<div class="tr"><div class="cell-main"><div><b>${esc(x.customer_name||'Walk-in customer')}</b><small><button type="button" class="link plain" data-act="open-order" data-id="${esc(x.order_id)}">${esc(x.order_number)}</button></small><small>${x.due_date?'Due '+fmtDate(x.due_date):'No due date'}</small></div></div><div class="hide-md num" data-label="Paid so far">${x.amount_paid>0?`${money(x.amount_paid)}<small class="muted" style="display:block">of ${money(x.original_amount)}</small>`:'<span class="muted">Nothing yet</span>'}</div><div class="num" data-label="Still owed"><b>${money(x.remaining_balance)}</b></div><div class="hide-md" data-label="Status">${pill(x.status)}${x.days_overdue>0?` <small class="muted">${x.days_overdue} day${x.days_overdue===1?'':'s'} late</small>`:''}</div><div class="phead-a"><button type="button" class="btn sm" data-act="edit-debt" data-id="${esc(x.id)}" title="Fix the amount or the due date">${ico('edit')}Correct</button>${(isPro()&&x.customer_id&&x.customer_phone)?sendBtn(debtAttrs(x),'Remind'):(wa?`<a class="btn sm" href="${esc(wa)}" target="_blank" rel="noopener noreferrer">${ico('chat')}Remind</a>`:'')}</div></div>`}).join('')}</div>`
    :(S.debts.items.length?emptyBox('search','No debts match','Try a different search or filter.'):emptyBox('debts','Nobody owes you money','Unpaid order balances appear here automatically.'))}</section>`}
ACT['dl-debts']=el=>{if(!isPro()){showUpgrade('debts_pdf');return}const fmt=el.dataset.fmt;download(`/api/debts/export?format=${fmt}`,`ojaloom-debts.${fmt}`,el,fmt==='pdf'?'Debt report downloaded.':'Spreadsheet downloaded.')};
ACT['edit-debt']=el=>openDebt(el.dataset.id);
function openDebt(id){
  const x=S.map.debts&&S.map.debts.get(id);if(!x)return;
  const body=`<form id="f-debt" data-form="debt" data-id="${esc(id)}" data-oid="${esc(x.order_id)}" data-cur="${x.remaining_balance}" data-total="${x.original_amount}" data-calc="debt"><div class="ferr"></div>
<div class="debt-card"><div><b>${esc(x.customer_name||'Walk-in customer')}</b><small>${esc(x.order_number)}${x.order_date?' · ordered '+fmtDate(x.order_date):''}</small></div><div class="mini"><div><span>Order total</span><b class="num">${money(x.original_amount)}</b></div><div><span>Paid so far</span><b class="num">${money(x.amount_paid)}</b></div><div><span>Owed now</span><b class="num">${money(x.remaining_balance)}</b></div></div></div>
<div class="field"><label for="d-bal">How much do they really owe?</label><div class="ig"><span>₦</span><input class="input" id="d-bal" name="remaining_balance" type="number" step="0.01" min="0" inputmode="decimal" required value="${x.remaining_balance}"></div><span class="hint" data-delta>Change the amount if you made a mistake.</span></div>
<div class="phead-a" style="margin:-6px 0 18px"><button type="button" class="btn sm" data-act="debt-zero">Write off the whole balance</button><button type="button" class="btn sm ghost" data-act="debt-reset" data-val="${x.remaining_balance}">Put it back</button></div>
<div class="field"><label for="d-due">Due date <span class="muted">(optional)</span></label><input class="input" id="d-due" type="date" name="due_date" value="${esc(x.due_date||'')}"></div>
${REASON_FIELD(DEBT_REASONS,'d-more')}
<div class="alert info">${ico('shield')}<span>The old amount, the new amount, who changed it and why are saved in your <button type="button" class="link" data-act="hist-for" data-id="${esc(x.order_id)}">edit history</button>. Nothing is overwritten silently.</span></div></form>`;
  const w=drawer({title:'Correct amount owed',body,foot:`<span></span><div class="grow"><button type="button" class="btn" data-act="close-layer">Cancel</button><button class="btn primary" type="submit" form="f-debt">Save correction</button></div>`});
  CALC.debt($('form',w))}
CALC.debt=f=>{
  const cur=parseFloat(f.dataset.cur)||0,tot=parseFloat(f.dataset.total)||0;const v=parseFloat(f.elements.remaining_balance.value);
  const hint=$('[data-delta]',f);const delta=isNaN(v)?0:Math.round((v-cur)*100)/100;
  $$('[data-reason]',f).forEach(e=>e.classList.toggle('hidden',delta===0));
  if(!hint)return;
  if(isNaN(v)){hint.className='hint';hint.textContent='Enter the amount they really owe.';return}
  if(delta===0){hint.className='hint';hint.textContent='Change the amount if you made a mistake.';return}
  hint.className='hint '+(delta<0?'ok':'bad');
  hint.textContent=delta<0?`That lowers what they owe by ${money(-delta)}. The order total goes from ${money(tot)} to ${money(tot+delta)}.`:`That raises what they owe by ${money(delta)}. The order total goes from ${money(tot)} to ${money(tot+delta)}.`};
ACT['debt-zero']=el=>{const f=el.closest('form');f.elements.remaining_balance.value='0';f.elements.remaining_balance.dispatchEvent(new Event('input',{bubbles:true}));const root=$('[data-reason] .dd',f);if(root)ddSet(root.dataset.dd,'Written off, will not be paid')};
ACT['debt-reset']=el=>{const f=el.closest('form');f.elements.remaining_balance.value=el.dataset.val;f.elements.remaining_balance.dispatchEvent(new Event('input',{bubbles:true}))};
ACT['hist-for']=el=>{closeLayers();go('history?entity='+encodeURIComponent(el.dataset.id))};
FORMS.debt=async f=>{
  const cur=parseFloat(f.dataset.cur)||0;const v=parseFloat(f.elements.remaining_balance.value);
  if(isNaN(v)||v<0)return formErr(f,'Enter the amount they really owe (0 or more).');
  const changed=Math.round((v-cur)*100)!==0;const reason=reasonText(f);
  if(changed&&reason.length<3)return formErr(f,'Choose a reason, or write one in the detail box. It is saved in your edit history.');
  const b={remaining_balance:f.elements.remaining_balance.value,due_date:f.elements.due_date.value||'',reason};
  const btn=$('button[type=submit][form=f-debt]');const label=btn?btn.textContent:'';busy(btn,true,'Saving…');
  try{await api('/api/debts/'+f.dataset.id,{method:'PUT',body:b});closeLayers();toast(changed?'Saved. The old amount is kept in your edit history.':'Due date saved.');if(S.route.view==='debts')LOAD.debts(S.route);else if(S.route.view==='orders'&&S.route.id)loadOrderDetail(S.route.id)}
  catch(e){formErr(f,e.message)}finally{busy(btn,false,label)}};

/* =========================== CUSTOMER EXTRAS =========================== */
ACT['cust-statement']=el=>{if(!isPro()){showUpgrade('statement_pdf');return}download(`/api/customers/${encodeURIComponent(el.dataset.id)}/statement`,'statement.pdf',el,'Statement downloaded.')};
ACT['cust-history']=el=>{closeLayers();go('history?entity='+encodeURIComponent(el.dataset.id))};

/* =========================== EDIT HISTORY =========================== */
const H_TYPES=[['order','Orders'],['payment','Payments'],['debt','Debts'],['expense','Expenses'],['product','Products'],['customer','Customers'],['business','Settings'],['account','Account'],['plan','Plan']];
LOAD.history=async r=>{
  const ent=r.q.entity||'';
  if(!S.hf||!S.back||S.hf.entity!==ent)S.hf={types:[],q:'',start:'',end:'',entity:ent,items:[],next:0,counts:{},chain:null,limited:false,limitDays:7};
  const f=S.hf;
  setPage(pageHead('Edit history','Every change to money, stock, customers and settings. Entries can never be edited or deleted.',`<button type="button" class="btn" data-act="dl-history" data-fmt="csv">${ico('download')}Spreadsheet${proTag()}</button><button type="button" class="btn primary" data-act="dl-history" data-fmt="pdf">${ico('pdf')}PDF${proTag()}</button>`)
    +`<div id="hbanner"></div><div class="tools"><div class="search">${ico('search')}<input class="input" type="search" placeholder="Search names, order numbers, reasons" data-live="history" aria-label="Search history" maxlength="80" value="${esc(f.q)}"></div><input class="input" id="hstart" type="date" value="${esc(f.start)}" aria-label="From" style="max-width:170px" data-live="hdates"><input class="input" id="hend" type="date" value="${esc(f.end)}" aria-label="To" style="max-width:170px" data-live="hdates"></div><div id="hchips" class="fchips"></div><div id="hlist">${skel(4)}</div><div id="hmore"></div>`);
  loadHistory(true)};
LIVE.history=v=>{S.hf.q=v;loadHistory(true)};
LIVE.hdates=()=>{S.hf.start=($('#hstart')||{}).value||'';S.hf.end=($('#hend')||{}).value||'';loadHistory(true)};
async function loadHistory(reset){
  const n=S.nav,f=S.hf;if(!f||!$('#hlist'))return;
  if(reset){f.items=[];f.next=0;$('#hlist').innerHTML=skel(4)}
  const p=new URLSearchParams();if(f.types.length)p.set('type',f.types.join(','));if(f.q)p.set('search',f.q);if(f.start)p.set('start',f.start);if(f.end)p.set('end',f.end);if(f.entity)p.set('entity_id',f.entity);if(f.next)p.set('before',f.next);if(reset)p.set('verify','1');p.set('limit','40');
  try{
    const d=await api('/api/activity?'+p);if(n!==S.nav||!$('#hlist'))return;
    f.items=f.items.concat(d.items);f.next=d.more?d.next:0;f.counts=d.counts||{};f.limited=!!d.limited;f.limitDays=d.limit_days||7;if(d.chain)f.chain=d.chain;
    renderHistory()
  }catch(e){if(n===S.nav&&$('#hlist'))$('#hlist').innerHTML=alertBox(e.message)}}
const hMoney=v=>money((Number(v)||0)/100);
function hVal(c,v){
  if(c.kind==='money')return hMoney(v);
  if(c.kind==='bool')return v?'Yes':'No';
  if(c.kind==='date')return v?fmtDate(v):'none';
  if(c.kind==='list')return Array.isArray(v)?v.join('; '):String(v||'');
  const s=String(v??'').trim();return s||'(empty)'}
function hChange(c,action){
  if(c.kind==='list'){
    const li=a=>(a&&a.length)?`<ul>${a.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>`:'<span class="muted">none</span>';
    return `<div class="chg"><span class="cl">${esc(c.label)}</span>${action==='create'?`<span class="to">${li(c.to)}</span>`:action==='delete'?`<span class="from">${li(c.from)}</span>`:`<span class="from">${li(c.from)}</span><span class="arr">→</span><span class="to">${li(c.to)}</span>`}</div>`}
  if(action==='create')return `<div class="chg"><span class="cl">${esc(c.label)}</span><span class="to">${esc(hVal(c,c.to))}</span></div>`;
  if(action==='delete')return `<div class="chg"><span class="cl">${esc(c.label)}</span><span class="from">${esc(hVal(c,c.from))}</span></div>`;
  return `<div class="chg"><span class="cl">${esc(c.label)}</span><span class="from">${esc(hVal(c,c.from))}</span><span class="arr">→</span><span class="to">${esc(hVal(c,c.to))}</span></div>`}
function hDay(d){
  const t=new Date();const y=new Date(t);y.setDate(t.getDate()-1);const k=x=>x.toLocaleDateString('en-CA');
  if(k(d)===k(t))return 'Today';if(k(d)===k(y))return 'Yesterday';return d.toLocaleDateString('en-NG',{weekday:'long',day:'numeric',month:'long',year:'numeric'})}
function hEntry(it){
  const d=new Date(it.created_at);const time=isNaN(d)?'':d.toLocaleTimeString('en-US',{hour:'numeric',minute:'2-digit',hour12:true}).toLowerCase();
  const sub=it.label&&!String(it.summary).includes(it.label)?`<div class="muted hsub">${esc(it.label)}</div>`:'';
  return `<article class="hitem"><div class="hmeta"><span class="htime">${esc(time)}</span><span class="htype t-${esc(it.type)}">${esc(it.type_label)}</span></div><div class="hbody"><div class="hsum"><b>${esc(it.summary)}</b></div>${sub}${it.changes&&it.changes.length?`<div class="hchg">${it.changes.map(c=>hChange(c,it.action)).join('')}</div>`:''}${it.reason?`<div class="hreason">Reason: ${esc(it.reason)}</div>`:''}</div><div class="hside"><span class="hact">${esc(it.action_label)}</span><small class="muted">${esc(it.actor||'')}</small></div></article>`}
function renderHistory(){
  const f=S.hf;if(!f||!$('#hlist'))return;
  const total=Object.values(f.counts||{}).reduce((a,b)=>a+b,0);
  $('#hchips').innerHTML=`<button type="button" class="fchip" data-act="hist-type" data-t="" aria-pressed="${f.types.length===0}">All${total?` <small>${total}</small>`:''}</button>`+H_TYPES.filter(t=>(f.counts||{})[t[0]]||f.types.includes(t[0])).map(t=>`<button type="button" class="fchip" data-act="hist-type" data-t="${t[0]}" aria-pressed="${f.types.includes(t[0])}">${t[1]} <small>${(f.counts||{})[t[0]]||0}</small></button>`).join('');
  let ban='';
  if(f.entity)ban+=`<div class="alert info">${ico('search')}<span class="grow">Showing only the changes to one record.</span><button type="button" class="link" data-act="hist-clear">Show everything</button></div>`;
  if(f.chain)ban+=f.chain.ok?`<div class="alert ok">${ico('shield')}<span><b>History is intact.</b> ${f.chain.checked.toLocaleString('en-NG')} entr${f.chain.checked===1?'y was':'ies were'} re-checked end to end. None has been altered or removed since it was recorded.</span></div>`:`<div class="alert">${ico('alert')}<span><b>The tamper check failed.</b> Some history was changed outside Oja Loom, around ${esc(fmtDate(f.chain.broken_at))}. Treat the figures from that date with care.</span></div>`;
  if(f.limited)ban+=`<div class="alert warn">${ico('lock')}<span class="grow">Your free plan shows the last ${f.limitDays} days of history. Pro shows everything and lets you download it.</span><button type="button" class="link" data-act="see-pro">Upgrade</button></div>`;
  $('#hbanner').innerHTML=ban;
  if(!f.items.length){$('#hlist').innerHTML=`<section class="panel">${(f.q||f.types.length||f.start||f.end||f.entity)?emptyBox('search','Nothing matches','Try clearing a filter or searching for something else.'):emptyBox('history','No changes recorded yet','When you add or edit orders, payments, debts, products or customers, each change appears here.')}</section>`;$('#hmore').innerHTML='';return}
  let html='',day='',open=false;
  f.items.forEach(it=>{const d=new Date(it.created_at);const label=isNaN(d)?'':hDay(d);
    if(label!==day){if(open)html+='</section>';html+=`<div class="hday">${esc(label)}</div><section class="panel">`;open=true;day=label}
    html+=hEntry(it)});
  if(open)html+='</section>';
  $('#hlist').innerHTML=html;
  $('#hmore').innerHTML=f.next?`<div style="text-align:center;margin-top:18px"><button type="button" class="btn" data-act="hist-more">Show older changes</button></div>`:''}
ACT['hist-type']=el=>{const t=el.dataset.t,f=S.hf;if(!t)f.types=[];else f.types=f.types.includes(t)?f.types.filter(x=>x!==t):f.types.concat(t);loadHistory(true)};
ACT['hist-more']=el=>{el.disabled=true;loadHistory(false)};
ACT['hist-clear']=()=>go('history');
ACT['dl-history']=el=>{
  if(!isPro()){showUpgrade('activity_export');return}
  const f=S.hf||{types:[]};const p=new URLSearchParams({format:el.dataset.fmt});if(f.types.length)p.set('type',f.types.join(','));if(f.q)p.set('search',f.q);if(f.start)p.set('start',f.start);if(f.end)p.set('end',f.end);
  download('/api/activity/export?'+p,`ojaloom-edit-history.${el.dataset.fmt}`,el,el.dataset.fmt==='pdf'?'History PDF downloaded.':'Spreadsheet downloaded.')};

/* =========================== OJA LOOM PRO (billing) =========================== */
const FREE_VS_PRO=a=>[['Products',`Up to ${a.limits.products}`,'Unlimited'],['Orders each month',`Up to ${a.limits.orders_per_month}`,'Unlimited'],['Edit history',`Last ${a.limits.activity_days} days`,'Everything, searchable, downloadable'],['Reports','Up to 31 days at a time','Any dates, as PDF or spreadsheet'],['PDF receipts, invoices and till slips','—','Included'],['Customer statements','—','Included'],['Debt reports','—','Included'],['Storefront','Shows “powered by Oja Loom”','Your brand only']];
LOAD.billing=async r=>{
  const n=S.nav;setPage(pageHead('Oja Loom Pro','Everything in Oja Loom, plus the tools that save you time.')+skel(3));
  try{
    const d=await api('/api/plan');if(n!==S.nav)return;const a=d.plan;if(S.biz)S.biz.access=a;
    if(r.q.paid){
      if(r.q.paid==='1'){try{const b=await api('/api/business');S.biz=b.business}catch(e){}renderApp();setTimeout(()=>toast('Payment received. Oja Loom Pro is active.'),300)}
      else setTimeout(()=>toast('We could not confirm that payment yet. If you were charged, it will appear here within a few minutes.',true),300);
      try{history.replaceState({i:hIndex},'','#/billing');S.shownHash='#/billing'}catch(e){}
      return LOAD.billing({view:'billing',id:'',q:{}})}
    const days=a.days_left;const dl=days==null?'':`${days} day${days===1?'':'s'} left`;
    const status=a.state==='pro'?`<span class="pill ok">Pro is active</span><h2>You have Oja Loom Pro</h2><p class="muted">Active until <b>${esc(fmtDate(a.ends_at))}</b>${dl?` (${esc(dl)})`:''}. Pay or redeem a code again to add ${a.period_days} more days on top.</p>`
      :a.state==='trial'?`<span class="pill gold">Free trial</span><h2>${esc(dl||'Trial running')}</h2><p class="muted">Every Pro feature is open during your trial. Choose Pro before it ends to keep them.</p>`
      :`<span class="pill">Free plan</span><h2>You are on the free plan</h2><p class="muted">Orders, stock, customers, debts and receipts all work. Pro adds the extras below.</p>`;
    const payBtn=d.online?`<button type="button" class="btn primary" data-act="pay-pro">${ico('billing')}Pay ${money(a.price,true)} now</button><span class="hint">Card, bank transfer or USSD, through Paystack.</span>`:'';
    const note=d.pay_note?`<div class="alert info" style="white-space:pre-wrap">${ico('shield')}<span>${esc(d.pay_note)}</span></div>`:'';
    const noWay=!d.online&&!d.pay_note?`<p class="hint" style="margin:0 0 14px">Ask whoever runs this Oja Loom for an activation code, then enter it below.</p>`:'';
    setPage(pageHead('Oja Loom Pro','Everything in Oja Loom, plus the tools that save you time.')
      +(a.enforced?'':`<div class="alert info">${ico('gift')}<span>Every Pro feature is open to everyone on this server right now. This page shows what Pro will include once plans are switched on.</span></div>`)
      +`<div class="cols even"><section class="panel plan-card ${a.state==='pro'?'on':''}"><div class="panel-b">${status}<div class="price-row"><span class="price-big num">${money(a.price,true)}</span><span class="muted">every ${a.period_days} days</span></div>${payBtn}${note}${noWay}
<form data-form="redeem" class="redeem"><div class="ferr"></div><label for="rd-code" class="lbl">Have an activation code?</label><div class="phead-a nowrap"><input class="input" id="rd-code" name="code" maxlength="40" placeholder="OJA-XXXX-XXXX-XXXX" autocomplete="off" autocapitalize="characters" spellcheck="false" required><button class="btn" type="submit">Activate</button></div></form></div></section>
<section class="panel"><div class="panel-h"><h2>What Pro adds</h2></div><div class="panel-b"><ul class="feat-list">${Object.values(a.features).map(f=>`<li>${ico('check')}<div><b>${esc(f.name)}</b><div class="muted">${esc(f.pitch)}</div></div></li>`).join('')}</ul></div></section></div>
<section class="panel" style="margin-top:18px"><div class="panel-h"><h2>Free and Pro side by side</h2></div><div class="scrollx"><table class="cmp"><thead><tr><th></th><th>Free</th><th>Pro</th></tr></thead><tbody>${FREE_VS_PRO(a).map(r=>`<tr><td><b>${esc(r[0])}</b></td><td class="muted">${esc(r[1])}</td><td class="y">${esc(r[2])}</td></tr>`).join('')}</tbody></table></div></section>
<section class="panel" style="margin-top:18px"><div class="panel-h"><h2>Payments</h2></div>${d.history.length?`<div class="tbl" style="--cols:140px minmax(0,1fr) 110px 120px;--cols-md:130px minmax(0,1fr) 110px"><div class="tr th"><div>Date</div><div>How</div><div>Days added</div><div class="hide-md right">Amount</div></div>${d.history.map(h=>`<div class="tr"><div data-label="Date">${esc(fmtDate(h.paid_at))}</div><div data-label="How">${h.provider==='code'?'Activation code':'Paystack'} <small class="muted">${esc(h.reference)}</small></div><div class="num" data-label="Days added">+${h.days}</div><div class="hide-md right num" data-label="Amount">${h.amount?money(h.amount,true):'—'}</div></div>`).join('')}</div>`:emptyBox('billing','No payments yet','Your Pro payments and activation codes will be listed here.')}</section>`)
  }catch(e){if(n===S.nav)setPage(alertBox(e.message))}};
ACT['pay-pro']=async el=>{
  const label=el.innerHTML;busy(el,true,'Opening payment…');
  try{const d=await api('/api/plan/checkout',{method:'POST',body:{}});location.href=d.url}catch(e){toast(e.message,true);el.disabled=false;el.innerHTML=label}};
FORMS.redeem=async f=>{
  const btn=$('button[type=submit]',f);busy(btn,true,'Checking…');
  try{const d=await api('/api/plan/redeem',{method:'POST',body:{code:f.elements.code.value}});S.biz=d.business;renderApp();showRoute();toast(`Oja Loom Pro is active. ${d.days} days added.`)}
  catch(e){formErr(f,e.message);busy(btn,false,'Activate')}};

/* =========================== TERMS OF SERVICE (accounts from before the Terms) =========================== */
function askTerms(){
  if(!S.me||S.me.terms_ok!==false||S.termsAsked)return;S.termsAsked=true;
  dialog(`<div class="row-b"><h2>Terms of Service</h2><button type="button" class="btn ghost icon" data-act="close-layer" aria-label="Close">${ico('x')}</button></div>
<p class="muted">Oja Loom now has Terms of Service. Please read them, then tap I agree to carry on. They cover your records, plans and payments, and how your data is used.</p>
<p style="margin:0"><a class="link plain" href="${U('/terms')}" target="_blank" rel="noopener">Read the Terms of Service</a></p>
<div class="dlg-act"><button type="button" class="btn" data-act="close-layer">Later</button><button type="button" class="btn primary" data-act="accept-terms">I agree</button></div>`,'Terms of Service')}
ACT['accept-terms']=async el=>{
  busy(el,true,'Saving…');
  try{const d=await api('/api/account/terms',{method:'POST',body:{}});S.me=d.user;closeLayers();toast('Thank you. Your agreement is saved.');if(S.route.view==='settings')showRoute()}
  catch(e){toast(e.message,true);busy(el,false,'I agree')}};

/* =========================== SEND PDFs INTO WHATSAPP (Web Share) =========================== */
const PDFC=new Map();
const canShareFiles=()=>typeof navigator.share==='function'&&typeof navigator.canShare==='function'&&typeof File==='function';
function pdfFetch(url){
  const h=PDFC.get(url);if(h&&Date.now()-h.t<45000)return h.p;
  const p=fetch(U(url),{credentials:'include'}).then(async r=>{
    if(!r.ok){let d={};try{d=await r.json()}catch(x){}const e=new Error(d.error||'Could not prepare the PDF.');e.status=r.status;e.upgrade=d.upgrade;throw e}
    const cd=r.headers.get('Content-Disposition')||'';const m=/filename="([^"]+)"/.exec(cd);
    return {blob:await r.blob(),name:m?m[1]:'document.pdf'}});
  PDFC.set(url,{t:Date.now(),p});p.catch(()=>PDFC.delete(url));return p}
const waChat=(phone,text)=>'https://wa.me/'+String(phone||'').replace(/\D/g,'')+'?text='+encodeURIComponent(text);
const waFirst=n=>String(n||'').trim().split(/\s+/)[0]||'';
function rcptAttrs(r){
  const f=waFirst(r.name),biz=S.biz?S.biz.name:'us';
  const sum=`Total ${money(r.total)}, ${r.bal>0?'balance due '+money(r.bal)+'.':'paid in full.'}`;
  const text=`Hello${f?' '+f:''}, thank you for your business. Here is your receipt ${r.num} from ${biz}. ${sum}`;
  const mail=`Hello${f?' '+f:''},\n\nThank you for your business. Your receipt ${r.num} from ${biz} is attached.\n${sum}\n\nKind regards,\n${biz}`;
  return ` data-pdf="${esc('/receipt/'+r.token+'/pdf?kind=receipt')}" data-phone="${esc(r.phone||'')}" data-title="${esc('Receipt '+r.num)}" data-text="${esc(text)}" data-link="${esc(text+' '+U('/receipt/'+r.token))}" data-feature="pdf_receipt" data-kind="receipt" data-ref="${esc(r.token)}" data-name="${esc(r.name||'')}" data-email="${esc(r.email||'')}" data-subject="${esc('Receipt '+r.num+' from '+biz)}" data-mail="${esc(mail)}"`}
function stmtAttrs(c){
  const f=waFirst(c.full_name),biz=S.biz?S.biz.name:'us',owe=Number(c.outstanding_debt)||0;
  const sum=owe>0?'Balance owing: '+money(owe)+'.':'Nothing is owing. Thank you.';
  const text=`Hello${f?' '+f:''}, here is your statement of account from ${biz}. ${sum}`;
  const mail=`Hello${f?' '+f:''},\n\nYour statement of account from ${biz} is attached.\n${sum}\n\nKind regards,\n${biz}`;
  return ` data-pdf="${esc('/api/customers/'+c.id+'/statement')}" data-phone="${esc(c.phone||'')}" data-title="${esc('Statement of account')}" data-text="${esc(text)}" data-feature="statement_pdf" data-kind="statement" data-ref="${esc(c.id)}" data-name="${esc(c.full_name||'')}" data-email="${esc(c.email||'')}" data-subject="${esc('Statement of account from '+biz)}" data-mail="${esc(mail)}"`}
const sendBtn=(attrs,label,cls)=>`<button type="button" class="btn ${cls||''} wasend" data-act="send-menu" aria-haspopup="menu"${attrs}>${ico('chat')}${label}<span class="caret">${ico('chev')}</span></button>`;
function saveBlob(blob,name){const u=URL.createObjectURL(blob);const a=document.createElement('a');a.href=u;a.download=name;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(u),8000)}
function openWa(url){const w=window.open(url,'_blank');if(w){try{w.opener=null}catch(x){}}return !!w}
function openMail(to,subject,body){const a=document.createElement('a');a.href='mailto:'+encodeURIComponent(to||'').replace(/%40/g,'@')+'?subject='+encodeURIComponent(subject||'')+'&body='+encodeURIComponent(body||'');document.body.appendChild(a);a.click();a.remove()}

/* Send a PDF: one "Send" menu, two choices. The PDF file itself travels (Pro); the free plan sends a link. */
let sendAnchor=null;
const SEND_KEYS=['pdf','phone','title','text','link','feature','kind','ref','name','email','subject','mail'];
const sendData=el=>SEND_KEYS.filter(k=>el.dataset[k]!==undefined).map(k=>` data-${k}="${esc(el.dataset[k])}"`).join('');
// the menu closes before the work starts, so "Preparing PDF…" is shown on the Send button that opened it
function sendBusy(on){
  const b=sendAnchor&&document.contains(sendAnchor)?sendAnchor:null;if(!b)return;
  if(on){if(b._label===undefined)b._label=b.innerHTML;b.disabled=true;b.textContent='Preparing PDF…'}
  else if(b._label!==undefined){b.disabled=false;b.innerHTML=b._label;b._label=undefined}}
ACT['send-menu']=el=>{
  if(ddOpenState&&ddOpenState.kind==='menu'){ddClose(true);return}
  sendAnchor=el;
  if(isPro()&&el.dataset.pdf)pdfFetch(el.dataset.pdf).catch(()=>{});   // prepare the PDF while the menu is open
  const a=sendData(el);
  popMenu(el,[{icon:'chat',label:'WhatsApp',run:'send-wa',attrs:a},{icon:'mail',label:'Email',run:'send-mail',attrs:a}],'Send PDF')};
// Hand the PDF file to the phone's share sheet (WhatsApp / the mail app attach it themselves). Where files cannot be shared
// (most desktops) the PDF is saved and the chat or email opens with the message already written.
async function sharePdf(d,channel){
  const mail=channel==='mail';
  sendBusy(true);
  try{
    const {blob,name}=await pdfFetch(d.pdf);
    const file=new File([blob],name,{type:'application/pdf'});
    if(canShareFiles()&&navigator.canShare({files:[file]})){
      try{await navigator.share(mail?{files:[file],title:d.subject||d.title||'',text:d.mail||d.text||''}:{files:[file],title:d.title||'',text:d.text||''});return}
      catch(e){if(e&&e.name==='AbortError')return}}
    saveBlob(blob,name);
    if(mail){openMail(d.email,d.subject||d.title,d.mail||d.text);toast('PDF saved to your downloads. Attach it in the email that just opened.')}
    else toast(openWa(waChat(d.phone,d.text))?'PDF saved to your downloads. Attach it in the WhatsApp chat that just opened.':'PDF saved to your downloads. Open WhatsApp and attach it.')
  }catch(e){
    if(e.status===402)showUpgrade(e.upgrade||d.feature||'pdf_receipt',e.message);else toast(e.message||'Could not prepare the PDF.',true)
  }finally{sendBusy(false)}}
ACT['send-wa']=async el=>{
  const d=el.dataset;
  if(!isPro()){
    if(!d.link){showUpgrade(d.feature||'pdf_receipt');return}
    openWa(waChat(d.phone,d.link));toast('WhatsApp opened with a link. Oja Loom Pro sends the PDF itself.');return}
  // When the server has a WhatsApp Business number, the PDF is delivered straight into the customer's WhatsApp.
  if(BOOT.share&&BOOT.share.whatsapp_direct&&d.phone&&d.ref&&(d.kind==='receipt'||d.kind==='statement')){
    if(!await confirmBox({title:'Send on WhatsApp?',text:`The PDF goes straight into ${d.name||'the customer'}\u2019s WhatsApp (${d.phone}). It is sent from the Oja Loom WhatsApp number.`,ok:'Send PDF'}))return;
    let err='';sendBusy(true);
    try{await api('/api/share/whatsapp',{method:'POST',body:{doc:d.kind,ref:d.ref}});sendBusy(false);toast('Sent. The PDF is in their WhatsApp.');return}
    catch(e){sendBusy(false);if(e.status===402)return;err=e.message||'WhatsApp could not deliver it.'}
    if(!await confirmBox({title:'Could not send on WhatsApp',text:`${err} Share the PDF from your phone instead?`,ok:'Share'}))return}
  await sharePdf(d,'wa')};
ACT['send-mail']=async el=>{
  const d=el.dataset;
  if(!isPro()){
    if(!d.link){showUpgrade(d.feature||'pdf_receipt');return}
    openMail(d.email,d.subject||d.title,d.link);toast('Your mail app opened with a link. Oja Loom Pro attaches the PDF itself.');return}
  await sharePdf(d,'mail')};
// start fetching the PDF as soon as a finger or pointer reaches the button, so the share sheet can open inside the tap
['pointerover','touchstart','focusin'].forEach(t=>document.addEventListener(t,ev=>{
  const b=ev.target&&ev.target.closest?ev.target.closest('[data-act="send-menu"]'):null;
  if(b&&b.dataset.pdf&&isPro()&&canShareFiles())pdfFetch(b.dataset.pdf).catch(()=>{})},{passive:true}));

/* =========================== EXPENSES =========================== */
const EXP_CATS=["Stock & supplies", "Transport & delivery", "Rent", "Salaries & wages", "Electricity & fuel", "Data & airtime", "Marketing & ads", "Packaging", "Repairs & maintenance", "Taxes & fees", "Other"];
const EXP_REASONS=['I typed the wrong amount','Wrong category','Wrong date','Entered twice by mistake','It was not a business cost','Other'];
const xDefault=()=>{const d=rangeDates('month');return {range:'month',start:d[0],end:d[1],category:'',q:''}};
const xExportBtns=()=>`<button type="button" class="btn" data-act="dl-expenses" data-fmt="csv" title="Open in Excel or Google Sheets">${ico('download')}Spreadsheet${proTag()}</button><button type="button" class="btn" data-act="dl-expenses" data-fmt="pdf">${ico('pdf')}PDF${proTag()}</button><button type="button" class="btn primary" data-act="new-expense">${ico('plus')}Add expense</button>`;
LOAD.expenses=async()=>{
  if(!S.xf||!S.back)S.xf=xDefault();
  const f=S.xf;
  const cfg={sm:true,value:f.range,label:'Date range',options:RANGES,onChange:v=>{const d=rangeDates(v);if(!d)return;f.range=v;f.start=d[0];f.end=d[1];$('#xstart').value=d[0];$('#xend').value=d[1];loadExpenses()}};
  const ccfg={sm:true,value:f.category,label:'Category',options:[{v:'',l:'All categories'}].concat(EXP_CATS.map(c=>({v:c,l:c}))),onChange:v=>{f.category=v;loadExpenses()}};
  setPage(pageHead('Expenses','What your business spends, so you can see the profit you really keep.',xExportBtns())
    +`<div id="xkpis"></div><div class="tools xt"><div class="search">${ico('search')}<input class="input" type="search" placeholder="Search details or who you paid" data-live="expenses" aria-label="Search expenses" maxlength="80" value="${esc(f.q)}"></div>${dd(cfg)}${dd(ccfg)}<input class="input" id="xstart" type="date" value="${esc(f.start)}" aria-label="From" style="max-width:150px" data-live="xdates"><input class="input" id="xend" type="date" value="${esc(f.end)}" aria-label="To" style="max-width:150px" data-live="xdates"></div><div id="xbody">${skel(3)}</div>`);
  S.xcfg=cfg;loadExpenses()};
LIVE.expenses=v=>{S.xf.q=v;loadExpenses()};
LIVE.xdates=()=>{const f=S.xf;const a=($('#xstart')||{}).value,z=($('#xend')||{}).value;if(!a||!z)return;f.start=a;f.end=z;f.range='custom';if(S.xcfg)ddSet(S.xcfg.id,'custom',true);loadExpenses()};
async function loadExpenses(){
  const n=S.nav,f=S.xf;if(!f||!$('#xbody'))return;
  const p=new URLSearchParams({start:f.start,end:f.end});if(f.category)p.set('category',f.category);if(f.q)p.set('search',f.q);
  const seq=S.xseq=(S.xseq||0)+1;
  try{
    const d=await api('/api/expenses?'+p);if(n!==S.nav||seq!==S.xseq||!$('#xbody'))return;
    S.expenses=d;S.map.expenses=new Map(d.items.map(x=>[x.id,x]));renderExpenses()
  }catch(e){if(n===S.nav&&seq===S.xseq&&$('#xbody')){$('#xkpis').innerHTML='';$('#xbody').innerHTML=alertBox(e.message)}}}
function renderExpenses(){
  const d=S.expenses,f=S.xf;if(!d||!$('#xbody'))return;
  const diff=d.period_total-d.prev_total;
  const cmp=d.prev_total>0?`${diff>=0?'Up':'Down'} ${Math.abs(Math.round(diff/d.prev_total*100))}% on the period before`:(d.period_total>0?'Nothing recorded before this':'No expenses in these dates');
  const net=d.net_profit;
  $('#xkpis').innerHTML=`<div class="kpis"><div class="kpi"><div class="k">Spent</div><div class="v num"${d.period_total>0?' style="color:var(--bad)"':''}>${money(d.period_total,true)}</div><div class="f">${esc(cmp)}</div></div><div class="kpi"><div class="k">Share of sales</div><div class="v num">${d.sales>0?(d.period_total/d.sales*100).toFixed(d.period_total/d.sales*100<10?1:0)+'%':'—'}</div><div class="f">Sales ${money(d.sales,true)}</div></div><div class="kpi"><div class="k">Estimated profit</div><div class="v num">${money(d.gross_profit,true)}</div><div class="f">Before expenses</div></div><div class="kpi"><div class="k">Net profit</div><div class="v num" style="color:var(--${net<0?'bad':'ok'})">${money(net,true)}</div><div class="f">After expenses</div></div></div>`;
  const mx=Math.max(1,...d.by_category.map(x=>x.total));
  const cats=d.by_category.length>1?`<section class="panel" style="margin-bottom:18px"><div class="panel-h"><h2>Where the money went</h2></div><div class="panel-b"><div class="bars">${d.by_category.map(x=>`<div class="hb"><div class="t"><b>${esc(x.category)}</b><span class="num">${money(x.total,true)}</span></div><div class="tr2"><i style="--w:${(x.total/mx*100).toFixed(1)}%"></i></div><small class="muted">${x.count} entr${x.count===1?'y':'ies'} · ${d.period_total>0?Math.round(x.total/d.period_total*100):0}%</small></div>`).join('')}</div></div></section>`:'';
  const filtered=f.category||f.q;
  const list=d.items.length?`<section class="panel"><div class="tbl" style="--cols:minmax(0,2fr) 150px 96px;--cols-md:minmax(0,2fr) 130px 90px"><div class="tr th"><div>Details</div><div>Amount</div><div></div></div>${d.items.map(x=>`<div class="tr"><div class="cell-main"><div><b>${esc(x.description||x.category)}</b><small><span class="xcat">${esc(x.category)}</span>${x.vendor?' · '+esc(x.vendor):''}</small><small>${fmtDate(x.spent_on)}</small></div></div><div class="num" data-label="Amount"><b>${money(x.amount)}</b></div><div><button type="button" class="btn sm" data-act="edit-expense" data-id="${esc(x.id)}">${ico('edit')}Edit</button></div></div>`).join('')}</div></section>`
    :`<section class="panel">${filtered?emptyBox('search','No expenses match','Try a different search or category.'):emptyBox('expenses','No expenses in these dates','Record rent, transport, restocking and other costs to see your real profit.')}</section>`;
  const more=d.truncated?`<div class="alert info" style="margin-top:14px">${ico('alert')}<span>Showing the latest ${d.items.length} entries. Narrow the dates, or download the spreadsheet to get every one.</span></div>`:'';
  $('#xbody').innerHTML=cats+list+more}
ACT['new-expense']=()=>openExpense();
ACT['edit-expense']=el=>openExpense(el.dataset.id);
function openExpense(id){
  const x=id&&S.map.expenses?S.map.expenses.get(id):null;if(id&&!x)return;
  const today=ymd(new Date());
  const cdd=dd({name:'category',value:x?x.category:'',emptyPh:!x,placeholder:'Choose a category',label:'Category',options:EXP_CATS.map(c=>({v:c,l:c}))});
  const body=`<form id="f-expense" data-form="expense" data-id="${esc(id||'')}"${x?` data-orig="${esc(JSON.stringify({amount:x.amount,category:x.category,description:x.description||'',vendor:x.vendor||'',spent_on:x.spent_on}))}"`:''}><div class="ferr"></div>
<div class="cols2"><div class="field"><label for="x-amt">Amount</label><div class="ig"><span>₦</span><input class="input" id="x-amt" name="amount" type="number" step="0.01" min="0.01" inputmode="decimal" required value="${x?x.amount:''}" autocomplete="off"></div></div><div class="field"><label for="x-date">Date</label><input class="input" id="x-date" type="date" name="spent_on" max="${today}" value="${esc(x?x.spent_on:today)}"></div></div>
<div class="field"><label>Category</label>${cdd}</div>
<div class="field"><label for="x-desc">What was it for? <span class="muted">(optional)</span></label><input class="input" id="x-desc" name="description" maxlength="200" value="${esc(x?x.description:'')}" placeholder="e.g. Fuel for deliveries" autocomplete="off"></div>
<div class="field"><label for="x-vendor">Paid to <span class="muted">(optional)</span></label><input class="input" id="x-vendor" name="vendor" maxlength="120" value="${esc(x?x.vendor:'')}" autocomplete="off"></div>
${x?`${REASON_FIELD(EXP_REASONS,'x-more')}<div class="alert info">${ico('shield')}<span>A reason is needed if you change or remove this expense. The old values stay in your edit history.</span></div>`:''}</form>`;
  drawer({title:x?'Correct an expense':'Add an expense',body,foot:`${x?`<button type="button" class="btn danger" data-act="del-expense" data-id="${esc(x.id)}">${ico('trash')}Remove</button>`:'<span></span>'}<div class="grow"><button type="button" class="btn" data-act="close-layer">Cancel</button><button class="btn primary" type="submit" form="f-expense">${x?'Save correction':'Save expense'}</button></div>`})}
function afterExpense(){if(S.route.view==='expenses')loadExpenses();else if(S.route.view==='dashboard')showRoute()}
FORMS.expense=async f=>{
  const id=f.dataset.id;const b={amount:f.elements.amount.value,category:f.elements.category.value,spent_on:f.elements.spent_on.value,description:f.elements.description.value.trim(),vendor:f.elements.vendor.value.trim()};
  if(!(parseFloat(b.amount)>0))return formErr(f,'Enter how much was spent.');
  if(!b.category)return formErr(f,'Choose a category.');
  if(id){
    const o=JSON.parse(f.dataset.orig);
    const changed=Math.round(parseFloat(b.amount)*100)!==Math.round(o.amount*100)||b.category!==o.category||b.description!==o.description||b.vendor!==o.vendor||b.spent_on!==o.spent_on;
    if(changed){b.reason=reasonText(f);if(b.reason.length<3)return formErr(f,'Choose a reason, or write one in the detail box. It is saved in your edit history.')}
    else{closeLayers();return}}
  const btn=$('button[type=submit][form=f-expense]');const label=btn?btn.textContent:'';busy(btn,true,'Saving…');
  try{await api('/api/expenses'+(id?'/'+id:''),{method:id?'PUT':'POST',body:b});closeLayers();toast(id?'Expense corrected. The change is in your edit history.':'Expense recorded.');afterExpense()}
  catch(e){formErr(f,e.message)}finally{busy(btn,false,label)}};
ACT['del-expense']=async el=>{
  const f=$('#f-expense');if(!f)return;const reason=reasonText(f);
  if(reason.length<3){formErr(f,'Choose a reason first, then remove the expense.');return}
  const x=S.map.expenses&&S.map.expenses.get(el.dataset.id);
  if(!await confirmBox({title:'Remove this expense?',text:`${x?money(x.amount):'This expense'} will be taken out of your totals. It stays in your edit history, with your reason.`,ok:'Remove expense',danger:true}))return;
  try{await api('/api/expenses/'+el.dataset.id,{method:'DELETE',body:{reason}});closeLayers();toast('Expense removed. It is kept in your edit history.');afterExpense()}catch(e){toast(e.message,true)}};
ACT['dl-expenses']=el=>{
  if(!isPro()){showUpgrade('expense_export');return}
  const f=S.xf||xDefault();const fmt=el.dataset.fmt;
  download(`/api/expenses/export?format=${fmt}&start=${encodeURIComponent(f.start)}&end=${encodeURIComponent(f.end)}`,`ojaloom-expenses.${fmt}`,el,fmt==='pdf'?'Expenses report downloaded.':'Spreadsheet downloaded. It opens in Excel or Google Sheets.')};

/* =========================== BACKUP =========================== */
ACT['dl-backup']=el=>download('/api/backup','ojaloom-backup.zip',el,'Backup downloaded. Keep it somewhere safe.');

/* =========================== STOCK ADJUSTMENTS =========================== */
const STOCK_REASONS=['New stock arrived','Recount: the number was wrong','Damaged or spoiled','Lost or stolen','Returned by a customer','Used or given away by me','Other'];
ACT['adjust-stock']=el=>{
  const x=S.map.products&&S.map.products.get(el.dataset.id);if(!x)return;
  const body=`<form id="f-stock" data-form="stock" data-id="${esc(x.id)}" data-cur="${x.stock_quantity}" data-calc="stock"><div class="ferr"></div>
<div class="debt-card"><div><b>${esc(x.name)}</b><small>Now ${x.stock_quantity} in stock</small></div></div>
<div class="field"><label>What happened?</label>${dd({name:'mode',value:'add',label:'What happened',options:[{v:'add',l:'Stock came in',h:'Add'},{v:'remove',l:'Stock went out',h:'Remove'},{v:'set',l:'I counted it',h:'Set exact number'}]})}</div>
<div class="field"><label for="s-qty">Quantity</label><input class="input" id="s-qty" name="quantity" type="number" step="1" min="0" inputmode="numeric" required autocomplete="off"><span class="hint" data-after>Enter a number.</span></div>
${REASON_FIELD(STOCK_REASONS,'s-more')}
<div class="alert info">${ico('shield')}<span>The old number, the new number, who changed it and why are saved in your edit history.</span></div></form>`;
  drawer({title:'Adjust stock',body,foot:`<span></span><div class="grow"><button type="button" class="btn" data-act="close-layer">Cancel</button><button class="btn primary" type="submit" form="f-stock">Save adjustment</button></div>`})};
CALC.stock=f=>{
  const cur=parseInt(f.dataset.cur,10)||0,q=parseInt(f.elements.quantity.value,10),mode=f.elements.mode.value;const h=$('[data-after]',f);if(!h)return;
  if(isNaN(q)||q<0){h.className='hint';h.textContent='Enter a number.';return}
  const nw=mode==='add'?cur+q:mode==='remove'?cur-q:q;
  h.className='hint '+(nw<0?'bad':nw<cur?'':'ok');h.textContent=`Stock goes from ${cur} to ${nw}.`};
FORMS.stock=async f=>{
  const mode=f.elements.mode.value,q=parseInt(f.elements.quantity.value,10);
  if(isNaN(q)||q<0||(mode!=='set'&&q===0))return formErr(f,'Enter how many units.');
  const reason=reasonText(f);if(reason.length<3)return formErr(f,'Choose a reason, or write one in the detail box. It is saved in your edit history.');
  const btn=$('button[type=submit][form=f-stock]');const label=btn?btn.textContent:'';busy(btn,true,'Saving…');
  try{await api('/api/products/'+f.dataset.id+'/stock',{method:'POST',body:{mode,quantity:q,reason}});closeLayers();toast('Stock updated. The change is in your edit history.');if(S.route.view==='products')refreshProducts()}
  catch(e){formErr(f,e.message)}finally{busy(btn,false,label)}};
ACT['prod-history']=el=>{closeLayers();go('history?entity='+encodeURIComponent(el.dataset.id))};
function debtAttrs(x){
  const f=waFirst(x.customer_name),biz=S.biz?S.biz.name:'us';
  const text=`Hello${f?' '+f:''}, a friendly reminder that your balance for ${x.order_number} is ${money(x.remaining_balance)}. Your statement of account from ${biz} is attached. Thank you.`;
  const mail=`Hello${f?' '+f:''},\n\nA friendly reminder that your balance for ${x.order_number} is ${money(x.remaining_balance)}. Your statement of account from ${biz} is attached.\n\nThank you,\n${biz}`;
  return ` data-pdf="${esc('/api/customers/'+x.customer_id+'/statement')}" data-phone="${esc(x.customer_phone||'')}" data-title="${esc('Statement of account')}" data-text="${esc(text)}" data-feature="statement_pdf" data-kind="statement" data-ref="${esc(x.customer_id)}" data-name="${esc(x.customer_name||'')}" data-email="${esc(x.customer_email||'')}" data-subject="${esc('Statement of account from '+biz)}" data-mail="${esc(mail)}"`}

/* =========================== SUPPORT =========================== */
const supportLink=()=>SUPPORT_WA?'https://wa.me/'+SUPPORT_WA+'?text='+encodeURIComponent('Hello Oja Loom support, I need help'+(S.biz&&S.biz.name?' with my shop "'+S.biz.name+'"':'')+'.'):'';
const supportNumber=()=>!SUPPORT_WA?'':SUPPORT_WA.startsWith('234')?'0'+SUPPORT_WA.slice(3).replace(/(\d{3})(\d{3})(\d{4})$/,'$1 $2 $3'):'+'+SUPPORT_WA;
function syncSupport(){
  const a=$('#support');if(!a)return;
  if(!SUPPORT_WA){a.hidden=true;return}
  if(!a.firstChild)a.innerHTML=ico('chat');
  a.href=supportLink();a.hidden=false}
// the link is refreshed just before it opens, so the message always names the shop that is signed in
document.addEventListener('click',e=>{if(e.target.closest&&e.target.closest('#support'))syncSupport()},true);
ACT.reload=()=>location.reload();
// The web app is useless without its server: say so plainly instead of drawing an empty page.
async function loadBoot(){
  try{
    const res=await fetch(U('/api/boot'),{credentials:'omit',headers:{'Accept':'application/json'}});
    if(!res.ok)throw new Error('boot '+res.status);
    Object.assign(BOOT,await res.json());return true
  }catch(e){
    syncSupport();
    $('#root').innerHTML=`<main class="boot-err"><h1>Cannot reach Oja Loom</h1><p class="muted">Check your internet connection and try again. If it keeps happening, chat with support and we will help.</p><div class="boot-act"><button type="button" class="btn primary" data-act="reload">Try again</button>${SUPPORT_WA?`<a class="btn" href="${esc(supportLink())}" target="_blank" rel="noopener noreferrer">${ico('chat')}Chat with support</a>`:''}</div></main>`;
    return false}}

/* =========================== BOOT =========================== */
(async()=>{
  let rewards=[];
  if(!await loadBoot())return;
  syncSupport();
  try{const d=await api('/api/me');if(d.user){S.me=d.user;S.biz=d.business;S.csrf=d.csrf;rewards=d.rewards||[]}}catch(e){}
  if(!S.me&&S.ref){S.refInfo=await lookupRef(S.ref);if(!S.refInfo)clearRef()}else if(S.me&&S.ref)clearRef();
  render();announceRewards(rewards);setTimeout(askTerms,900)})();
})();

