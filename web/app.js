'use strict';
const base = new URL('.', location.href).pathname;
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const statusLabel = {running:'Проверка идёт', paused:'Приостановлено', completed:'Обход завершён', limited:'Достигнут лимит', failed:'Не удалось завершить'};
const severityLabel = {error:'Ошибка', warning:'Внимание', info:'Контекст'};
const date = value => new Date(value).toLocaleString('ru-RU');
let token = '', projects = [], project = null, run = null, runId = '', pollTimer, generation = 0;
function message(text, error=false) { $('message').textContent=text; $('message').className=error?'error':''; $('message').hidden=false; }
async function api(path, data) {
  const res=await fetch(base + path.replace(/^\//,''), data === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json','X-SEO-Token':token},body:JSON.stringify(data)});
  const body=await res.json(); if(!res.ok) throw new Error(body.error || 'Не удалось выполнить запрос'); return body;
}
async function action(button, fn) { button.disabled=true; try {await fn();} catch(e){message(e.message,true);} finally{button.disabled=button.id==='start'&&run?.status==='running';} }
function projectNav(){
  $('project-count').textContent=projects.length;
  $('projects').innerHTML=projects.map(p=>`<button type="button" data-project="${esc(p.id)}" ${project?.id===p.id?'aria-current="page"':''}>${esc(p.name)}<small>${esc(p.url)}</small></button>`).join('');
  $('projects').querySelectorAll('button').forEach(b=>b.onclick=()=>selectProject(b.dataset.project));
}
async function selectProject(id){
  const ticket=++generation;clearTimeout(pollTimer);project=projects.find(p=>p.id===id);run=null;runId='';
  if(!project)return;
  $('welcome').hidden=true;$('project-view').hidden=false;$('project-title').textContent=project.name;$('project-url').textContent=project.url;$('project-url').href=project.url;
  $('result').hidden=true;$('no-runs').hidden=false;$('imports').innerHTML='';$('severity').value='all';$('search').value='';$('rule-family').value='all';$('lh-url').value=project.url;projectNav();
  document.dispatchEvent(new CustomEvent('seo:change',{detail:'project-view'}));
  try{await Promise.all([loadHistory(ticket),loadImports(ticket)]);}catch(e){message(e.message,true);}
}
async function loadHistory(ticket=generation){
  const list=await api('/api/runs?project='+project.id);if(ticket!==generation)return;
  $('history').innerHTML=list.length?list.map(r=>`<option value="${esc(r.id)}">${esc(date(r.created))} · ${esc(statusLabel[r.status])} · ${r.checked}</option>`).join(''):'<option value="">Проверок пока нет</option>';
  if(list.length){runId=list.some(r=>r.id===runId)?runId:list[0].id;$('history').value=runId;await loadRun(ticket);}
  else{$('start').disabled=false;$('result').hidden=true;$('no-runs').hidden=false;}
}
async function loadRun(ticket=generation){
  clearTimeout(pollTimer);const id=runId;if(!id)return;
  const data=await api('/api/run?id='+id);if(ticket!==generation||id!==runId)return;run=data;renderRun();
  if(run.status==='running')pollTimer=setTimeout(()=>loadRun(ticket).catch(e=>message(e.message,true)),1500);
}
function renderRun(){
  const option=Array.from($('history').options).find(o=>o.value===run.id);if(option)option.textContent=`${date(run.created)} · ${statusLabel[run.status]} · ${run.pages.length}`;
  $('result').hidden=false;$('no-runs').hidden=true;$('run-status').textContent=statusLabel[run.status]||run.status;$('run-message').textContent=run.message;
  $('pause').hidden=run.status!=='running';$('resume').hidden=run.status!=='paused';$('start').disabled=run.status==='running';
  const s=run.summary;$('metrics').innerHTML=[[s.checked,'проверено адресов'],[s.error,'ошибок'],[s.warning,'предупреждений'],[s.unavailable,'не удалось проверить']].map(([n,l])=>`<div class="metric"><strong>${n}</strong><span>${l}</span></div>`).join('');
  const c=run.comparison;$('comparison').hidden=!c;if(c)$('comparison').textContent=`С предыдущей проверкой: ${c.new.length} новых замечаний, ${c.resolved.length} больше не обнаружено, ${c.not_rechecked.length} не перепроверено. Общих HTML-страниц: ${c.common_pages}. ${c.note}`;
  for(const format of ['html','csv','json'])$(format+'-export').href=`${base}api/export?id=${run.id}&format=${format}`;
  $('pages-title').textContent=`Проверенные адреса (${run.pages.length}) · в очереди ${s.pending}`;
  $('pages').innerHTML=run.pages.map(p=>`<tr><td><a href="${esc(p.url)}" target="_blank" rel="noopener noreferrer">${esc(p.url)}</a>${p.error?`<p>${esc(p.error)}</p>`:''}</td><td>${p.status||'—'}</td><td>${esc(p.title||'—')}</td><td>${esc(p.h1?.join(' / ')||'—')}</td></tr>`).join('');
  const checked=new Set(run.pages.filter(p=>!p.error&&!p.blocked&&!p.truncated&&p.status).map(p=>p.url));
  const maps=[...new Set(run.sitemap_urls||[])];
  $('coverage').textContent=`Охват Sitemap: ${maps.filter(u=>checked.has(u)).length} из ${maps.length} прочитанных адресов проверено. Внешние и не посещённые цели отмечены отдельно.`;
  renderIssues();
}
function renderIssues(){if(!run)return;const filter=$('severity').value,q=$('search').value.toLowerCase();const family=$('rule-family').value;const list=run.issues.filter(i=>(family==='all'||i.code.startsWith(family)||family==='schema'&&i.code.startsWith('jsonld'))&&(filter==='all'||i.severity===filter)&&`${i.url} ${i.title} ${i.code} ${i.evidence}`.toLowerCase().includes(q));
  $('issues').innerHTML=list.length?list.map(i=>`<article class="issue"><span class="badge ${i.severity}">${severityLabel[i.severity]}</span><div><h3>${esc(i.title)}</h3><a class="issue-url" href="${esc(i.url)}" target="_blank" rel="noopener noreferrer">${esc(i.url)}</a><div class="evidence">${esc(i.evidence)}</div><p class="action">${esc(i.action)}</p></div></article>`).join(''):'<p class="empty">По выбранному фильтру замечаний нет. Проверьте охват и ошибки загрузки.</p>';
}
async function loadImports(ticket=generation){const data=await api('/api/imports?project='+project.id);if(ticket!==generation)return;
  $('imports').innerHTML=data.map(r=>`<article class="import-record"><strong>${esc(r.start)} — ${esc(r.end)}</strong><p>${r.summary.rows} строк · ${r.summary.clicks} кликов · ${r.summary.impressions} показов · CTR ${r.summary.ctr===null?'—':(r.summary.ctr*100).toFixed(2)+'%'} · средняя позиция ${r.summary.position===null?'—':r.summary.position.toFixed(2)}</p><p class="hint">${esc(r.note)}</p></article>`).join('');
}
$('project-form').onsubmit=e=>{e.preventDefault();const form=e.currentTarget;action(form.querySelector('button'),async()=>{const f=new FormData(form);const p=await api('/api/projects',{name:f.get('name'),url:f.get('url')});projects=await api('/api/projects');form.reset();$('new-project').open=false;await selectProject(p.id);$('audit').scrollIntoView({block:'start'});message('Проект добавлен. Можно запустить проверку.');});};
$('run-form').onsubmit=e=>{e.preventDefault();const f=new FormData(e.currentTarget);action($('start'),async()=>{const result=await api('/api/start',{project:project.id,limit:Number(f.get('limit')),delay:Number(f.get('delay'))});runId=result.id;await loadHistory();message('Проверка запущена. Результаты сохраняются после каждого адреса.');});};
$('pause').onclick=()=>action($('pause'),async()=>{const r=await api('/api/pause',{id:runId});message(r.message);});
$('resume').onclick=()=>action($('resume'),async()=>{await api('/api/resume',{id:runId});await loadRun();});
$('history').onchange=()=>{runId=$('history').value;loadRun().catch(e=>message(e.message,true));};
$('rule-family').onchange=renderIssues;$('severity').onchange=renderIssues;$('search').oninput=renderIssues;
$('import-form').onsubmit=e=>{e.preventDefault();const f=new FormData(e.currentTarget);action(e.currentTarget.querySelector('button'),async()=>{const file=f.get('file');if(file.size>5000000)throw new Error('CSV должен быть меньше 5 МБ');const csv=await file.text();await api('/api/import',{project:project.id,csv,start:f.get('from'),end:f.get('to')});await loadImports();message('CSV импортирован. Показаны итоги строк выгрузки.');});};
$('backup').onclick=()=>action($('backup'),async()=>{const r=await api('/api/backup',{});message('Резервная копия сохранена: '+r.path);});
$('shutdown').onclick=()=>action($('shutdown'),async()=>{await api('/api/shutdown',{});clearTimeout(pollTimer);message('Приложение остановлено. Для запуска используйте start.cmd.');document.querySelectorAll('button,input,select').forEach(e=>e.disabled=true);});
(async()=>{try{const session=await api('/api/session');token=session.token;$('shutdown').hidden=session.hosted;$('lh-capability').textContent=session.lighthouse.message;$('lh-start').disabled=!session.lighthouse.available;projects=await api('/api/projects');projectNav();if(projects.length){$('new-project').open=false;await selectProject(projects[0].id);}}catch(e){message('Не удалось подключиться к локальному серверу: '+e.message,true);}})();

$('schema-form').onsubmit=e=>{e.preventDefault();action(e.currentTarget.querySelector('button'),async()=>{const r=await api('/api/schema',{text:$('schema-text').value});$('schema-result').innerHTML=`<p>Объектов: ${r.nodes}. Типы: ${esc(r.types.join(', ')||'не обнаружены')}. ${r.complete?'Проверки выполнены в пределах поддерживаемого формата.':'Есть непроверенные части.'}</p>`+r.issues.map(i=>`<p><strong>${esc(i.path)}</strong> — ${esc(i.detail)}</p>`).join('')+`<p class="hint">${esc(r.note||'Исправьте синтаксис JSON.')}</p>`;});};
let lhTimer;
async function loadLighthouse(id){
  clearTimeout(lhTimer);const r=await api('/api/lighthouse?id='+encodeURIComponent(id));
  if(r.status==='running'){$('lh-result').textContent='Lighthouse выполняется…';lhTimer=setTimeout(()=>loadLighthouse(id).catch(e=>message(e.message,true)),2000);return;}
  if(r.status==='failed'){$('lh-result').textContent=r.error;return;}
  const s=r.summary;$('lh-result').innerHTML=`<p>${esc(s.url)} · ${esc(s.mode)} · Lighthouse ${esc(s.version)}</p><div class="metrics">${Object.entries(s.scores).map(([k,v])=>`<div class="metric"><strong>${v??'—'}</strong><span>${esc(k)}</span></div>`).join('')}</div><ul>${Object.entries(s.metrics).map(([k,v])=>`<li>${esc(k)}: ${esc(v.display)}</li>`).join('')}</ul><p class="hint">${esc(s.note)}</p><a href="${base}api/lighthouse/export?id=${encodeURIComponent(id)}">Скачать полный JSON</a>`;
}
$('lh-form').onsubmit=e=>{e.preventDefault();action($('lh-start'),async()=>{const r=await api('/api/lighthouse/start',{url:$('lh-url').value,mode:$('lh-mode').value});sessionStorage.setItem('seo-lighthouse-id',r.id);await loadLighthouse(r.id);});};
$('lh-import').onclick=()=>action($('lh-import'),async()=>{const f=$('lh-file').files[0];if(!f||f.size>5000000)throw new Error('Выберите JSON до 5 МБ');const r=await api('/api/lighthouse/import',{report:JSON.parse(await f.text())});sessionStorage.setItem('seo-lighthouse-id',r.id);await loadLighthouse(r.id);});
const lastLighthouse=sessionStorage.getItem('seo-lighthouse-id');if(lastLighthouse)loadLighthouse(lastLighthouse).catch(()=>sessionStorage.removeItem('seo-lighthouse-id'));

$('focus-project').onclick=()=>{$('new-project').open=true;$('new-project').scrollIntoView({block:'center'});$('project-form').elements.name.focus({preventScroll:true});};
