'use strict';
const providerNames={google:'Google Search Console',yandex:'Яндекс Вебмастер'};
async function connectionsStatus(){
 const state=await api('/api/connections');
 $('connection-cards').innerHTML=state.map(c=>`<article class="connection-card"><h3>${esc(c.name)}</h3><p class="connection-state">${c.connected?'Аккаунт подключён':c.configured?'Настройки сохранены. Нужен вход.':'Ожидает настройки'}</p><label>Redirect URI<input readonly value="${esc(c.redirect_uri)}" aria-label="Redirect URI ${esc(c.name)}"></label><p class="hint">Право: ${esc(c.scope)}</p><details ${c.configured?'':'open'}><summary>Настройки приложения</summary><form data-config="${c.provider}" autocomplete="off"><label>Client ID<input name="client_id" required autocomplete="off" spellcheck="false"></label><label>Client Secret<input name="client_secret" type="password" required autocomplete="new-password"></label><button class="quiet">Сохранить настройки</button><p class="hint">Повторное сохранение заменит настройки и потребует нового входа. Секрет не отображается после сохранения.</p></form></details><div class="connection-actions"><button data-connect="${c.provider}" ${c.configured?'':'disabled'}>${c.connected?'Войти заново':'Подключить аккаунт'}</button><button class="text-button" data-disconnect="${c.provider}" ${c.configured?'':'hidden'}>Удалить подключение</button></div></article>`).join('');
 $('connection-cards').querySelectorAll('[data-config]').forEach(form=>form.onsubmit=e=>{e.preventDefault();action(form.querySelector('button'),async()=>{const f=new FormData(form);const result=await api('/api/connections/configure',{provider:form.dataset.config,client_id:f.get('client_id'),client_secret:f.get('client_secret')});form.reset();await connectionsStatus();clearSites();message(result.message);});});
 $('connection-cards').querySelectorAll('[data-connect]').forEach(button=>button.onclick=()=>action(button,async()=>{
  if(button.dataset.connect!=='yandex'){const result=await api('/api/connections/start',{provider:button.dataset.connect});location.assign(result.url);return;}
  const result=await api('/api/connections/yandex/code/start',{});
  const card=button.closest('.connection-card');card.querySelector('[data-code-panel]')?.remove();
  const panel=document.createElement('div');panel.dataset.codePanel='';
  panel.innerHTML='<p>Откройте Яндекс, разрешите чтение данных и перенесите одноразовый код сюда. Срок — 10 минут. Не отправляйте код в чат.</p><p><a target="_blank" rel="noopener noreferrer">Открыть Яндекс ↗</a></p><form autocomplete="off"><label>Одноразовый код Яндекса<input name="code" type="password" required maxlength="4096" autocomplete="off"></label><button>Завершить подключение Яндекса</button></form>';
  panel.querySelector('a').href=result.url;
  const form=panel.querySelector('form');form.onsubmit=e=>{e.preventDefault();action(form.querySelector('button'),async()=>{
   const code=form.elements.code.value;form.reset();
   try{const done=await api('/api/connections/yandex/code/complete',{state:result.state,code});await connectionsStatus();clearSites();message(done.message);}
   catch(error){panel.remove();throw error;}
  });};card.append(panel);
 }));
 $('connection-cards').querySelectorAll('[data-disconnect]').forEach(button=>button.onclick=()=>action(button,async()=>{const result=await api('/api/connections/disconnect',{provider:button.dataset.disconnect});await connectionsStatus();clearSites();message(result.message);}));
}
let siteGeneration=0;
function clearSites(){siteGeneration++;$('sync-site').innerHTML='<option value="">Сначала загрузите список сайтов</option>';}
$('sync-provider').onchange=clearSites;
$('load-sites').onclick=()=>action($('load-sites'),async()=>{const ticket=++siteGeneration;const provider=$('sync-provider').value;const sites=await api('/api/connections/sites',{provider});if(ticket!==siteGeneration)return;$('sync-site').innerHTML='<option value="">Выберите сайт из кабинета</option>'+sites.map(s=>`<option value="${esc(s.id)}" ${s.verified?'':'disabled'}>${esc(s.label)}${s.verified?'':' — права не подтверждены'}</option>`).join('');message(sites.length?`Получено сайтов: ${sites.length}. Выберите нужный.`:'В этом аккаунте пока нет доступных сайтов. Проверьте доступ в кабинете провайдера.');});
$('sync-form').onsubmit=e=>{e.preventDefault();action($('sync-start'),async()=>{if(!project)throw Error('Сначала выберите или создайте проект');const projectId=project.id,provider=$('sync-provider').value;const result=await api('/api/connections/sync',{provider,project:projectId,site:$('sync-site').value,start:$('sync-from').value,end:$('sync-to').value});$('sync-result').textContent=`${providerNames[provider]}: сохранено ${result.rows.length} строк за ${result.start} — ${result.end}. ${result.note}`;if(project?.id===projectId)await loadImports();message('Поисковые данные сохранены в истории проекта.');});};
function syncProject(){ $('sync-project').textContent=project?`Сохранить в проект: ${project.name} · ${project.url}`:'Сначала выберите или создайте проект.'; }
document.addEventListener('seo:project',syncProject);syncProject();
const last=new Date();last.setDate(last.getDate()-3);const first=new Date(last);first.setDate(first.getDate()-27);const iso=d=>`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;$('sync-to').value=iso(last);$('sync-from').value=iso(first);
connectionsStatus().catch(e=>message(e.message,true));
const connectionParams=new URLSearchParams(location.search);
if(connectionParams.has('connection')){const ok=connectionParams.get('result')==='connected';message(ok?'Аккаунт подключён. Нажмите «Получить сайты» в разделе подключений.':'Авторизация не завершена. Проверьте Redirect URI, доступные права и тестовых пользователей. Начните вход заново в этом браузере.',!ok);history.replaceState(null,'',location.pathname+'#connections');}
