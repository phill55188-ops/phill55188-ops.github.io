(function () {
  'use strict';
  const root = document.getElementById('sb');
  const results = document.getElementById('sb-results');
  if (!root || !results) return;
  const MAX_FILES = 3, MAX_BYTES = 4 * 1024 * 1024;
  const TYPES = {txt:'text/plain',md:'text/markdown',csv:'text/csv',json:'application/json',pdf:'application/pdf',png:'image/png',jpg:'image/jpeg',jpeg:'image/jpeg',webp:'image/webp'};
  let context = null, sessions = new Map(), active = null, controller = null, generation = 0, reading = false, returnFocus = null;
  const dialog = document.createElement('dialog');
  dialog.className = 'followup-dialog';
  dialog.setAttribute('aria-labelledby','sb-followup-title');
  dialog.innerHTML = `<div class="followup-inner">
    <header class="followup-top"><div><div class="followup-kicker">SignalBrief · Follow-up research</div><h2 id="sb-followup-title"></h2></div><button type="button" class="act quiet followup-close" aria-label="Close follow-up">×</button></header>
    <p class="followup-note">Explore this section with OpenAI and fresh web research. Answers distinguish evidence, possibilities, and unknowns. Your question, section context, and any attached files are sent to OpenAI through your secure backend.</p>
    <details class="followup-context"><summary>Original section analysis</summary><pre id="sb-followup-context"></pre></details>
    <form id="sb-followup-form"><label for="sb-followup-question">Your follow-up question</label><textarea id="sb-followup-question" maxlength="4000" placeholder="What could change this conclusion?" required></textarea>
    <div class="followup-files" id="sb-followup-files"></div>
    <div class="followup-actions"><button type="button" class="act quiet" id="sb-followup-add">+ Add evidence</button><button type="button" class="act quiet" id="sb-followup-cancel" hidden>Cancel research</button><button type="submit" class="act primary" id="sb-followup-submit">Research question</button></div>
    <input id="sb-followup-upload" type="file" accept=".txt,.md,.csv,.json,.pdf,.png,.jpg,.jpeg,.webp" multiple hidden>
    <p class="followup-note">Evidence is optional · Up to 3 files, 4 MB each · Text, Markdown, CSV, JSON, PDF, PNG, JPEG, WebP. Text evidence: 120,000 characters total.</p></form>
    <p class="followup-status" role="status" aria-live="polite" id="sb-followup-status"></p>
    <div class="followup-answer-heading"><span>Research response</span><span id="sb-followup-length" class="hint"></span></div>
    <div class="followup-answer" id="sb-followup-answer" tabindex="0" role="region" aria-label="Research response"><p>Your answer will appear here.</p></div>
  </div>`;
  root.appendChild(dialog);
  const $ = id => document.getElementById('sb-followup-' + id);
  const question = $('question'), submit = $('submit'), add = $('add'), upload = $('upload'), cancel = $('cancel'), answer = $('answer'), files = $('files'), status = $('status');
  function message(text, error=false) { status.textContent=text; status.dataset.error=String(error); }
  function busy(on) { submit.disabled=on; add.disabled=on; question.disabled=on; cancel.hidden=!on; answer.setAttribute('aria-busy',String(on)); files.querySelectorAll('button').forEach(b=>b.disabled=on); }
  function renderFiles() {
    files.replaceChildren();
    if (!active) return;
    active.evidence.forEach((file,i)=>{
      const chip=document.createElement('span'); chip.className='followup-file';
      const name=document.createElement('span'); name.textContent=file.name; chip.append(name);
      const remove=document.createElement('button'); remove.type='button'; remove.textContent='×'; remove.setAttribute('aria-label','Remove '+file.name);
      remove.onclick=()=>{ active.evidence.splice(i,1); renderFiles(); message('Evidence removed. You can research without attachments.'); };
      chip.append(remove); files.append(chip);
    });
  }
  function safeURL(value) { try {const u=new URL(value); return /^https?:$/.test(u.protocol) ? u.href : null;} catch {return null;} }
  function renderAnswers() {
    answer.replaceChildren();
    if (!active.history.length) { const p=document.createElement('p'); p.textContent='Your answer will appear here. No evidence attachment is required.'; answer.append(p); }
    active.history.forEach(turn=>{
      const article=document.createElement('article'); article.className='followup-turn';
      const heading=document.createElement('h3'); heading.textContent=turn.question; article.append(heading);
      const p=document.createElement('p'); p.textContent=turn.answer; article.append(p);
      if (turn.citations.length) {
        const sources=document.createElement('div'); sources.className='followup-sources'; sources.textContent='Sources consulted';
        turn.citations.forEach((c,i)=>{ const url=safeURL(c.url); if(!url)return; const link=document.createElement('a');link.href=url;link.target='_blank';link.rel='noopener noreferrer';link.textContent=(i+1)+'. '+(c.title||new URL(url).hostname); sources.append(link); }); article.append(sources);
      }
      if (turn.incomplete) {const note=document.createElement('p');note.textContent='This response reached the service output limit. Ask a narrower follow-up to explore the remaining detail.';article.append(note);}
      if (!turn.webSearchUsed) {const note=document.createElement('p');note.textContent='No web search was confirmed for this answer. Treat it as analysis of the supplied context.';article.append(note);}
      answer.append(article);
    });
    requestAnimationFrame(()=>{
      const turns=answer.querySelectorAll('.followup-turn');
      answer.scrollTop=turns.length>1 ? turns[turns.length-1].offsetTop-turns[0].offsetTop : 0; $('length').textContent=answer.scrollHeight>answer.clientHeight+1?'Scroll to read more':''; });
  }
  function stop(text) { generation++; if(controller)controller.abort(); controller=null; busy(false); if(text)message(text); }
  function close() { if(active)active.draft=question.value; stop(); dialog.close(); if(returnFocus?.isConnected)returnFocus.focus(); }
  dialog.querySelector('.followup-close').onclick=close;
  dialog.addEventListener('cancel',e=>{e.preventDefault();close();});
  cancel.onclick=()=>stop('Research canceled. Your question and evidence are ready to retry.');
  question.addEventListener('input',()=>{if(active)active.draft=question.value;});
  add.onclick=()=>upload.click();
  async function fileData(file,type) {
    if(type.startsWith('text/')||type==='application/json')return file.text();
    return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=()=>reject(new Error('Could not read '+file.name));reader.readAsDataURL(file);});
  }
  upload.addEventListener('change',async()=>{
    if (!active || controller) return;
    const session=active, selected=Array.from(upload.files); upload.value='';
    if (session.evidence.length+selected.length>MAX_FILES) {message('Choose up to 3 files. Remove an existing attachment first.',true);return;}
    reading=true;submit.disabled=true;add.disabled=true;
    try {
      const pending=[];
      for (const file of selected) {
        const extension=file.name.split('.').pop().toLowerCase(),type=TYPES[extension];
        if(!type)throw new Error('Unsupported file: '+file.name+'. Choose TXT, MD, CSV, JSON, PDF, PNG, JPEG, or WebP.');
        if(!file.size)throw new Error(file.name+' is empty. Choose another file or continue without evidence.');
        if(file.size>MAX_BYTES)throw new Error(file.name+' exceeds 4 MB. Choose a smaller file or continue without evidence.');
        pending.push({name:file.name,type,data:await fileData(file,type)});
      }
      const combined=[...session.evidence,...pending];
      if(combined.filter(f=>f.type.startsWith('text/')||f.type==='application/json').reduce((n,f)=>n+f.data.length,0)>120000)throw new Error('Text evidence exceeds 120,000 characters. Use smaller excerpts or continue without evidence.');
      session.evidence=combined;
      if(active===session){renderFiles();message('Evidence ready. Add your question to research it.');}
    } catch(err) {if(active===session)message(err.message,true);}
    finally {reading=false;submit.disabled=false;add.disabled=false;}
  });
  $('form').addEventListener('submit',async e=>{
    e.preventDefault();
    if(controller||reading||!active)return;
    const text=question.value.trim();if(!text){message('Enter a follow-up question.',true);question.focus();return;}
    const backend=document.getElementById('sb-backend-url').value.trim().replace(/\/+$/,''),access=document.getElementById('sb-access-token').value.trim();
    if(!backend||!access){message('Open Backend connection on the main page, enter your existing access code, and test the connection.',true);return;}
    const session=active, current=++generation;
    controller=new AbortController(); const signal=controller.signal;
    const timer=setTimeout(()=>controller?.abort(),240000);
    busy(true);message('Researching the evidence, alternatives, and counterarguments…');
    try {
      const response=await fetch(backend+'/api/followup',{method:'POST',headers:{'Content-Type':'application/json','X-SignalBrief-Access':access},signal,body:JSON.stringify({question:text,section:session.section,context,history:session.history.slice(-6).map(t=>({question:t.question,answer:t.answer})),evidence:session.evidence})});
      const data=await response.json().catch(()=>({}));
      if(!response.ok)throw new Error(response.status===401?'Your backend access code was rejected. Check Backend connection.':response.status===404?'The backend follow-up update is not deployed yet. Try again after deployment.':String(data.error||'The research service returned HTTP '+response.status+'. Try again.'));
      if(!String(data.text||'').trim())throw new Error('The research service returned an empty response. Try again.');
      if(current!==generation)return;
      session.history.push({question:text,answer:data.text,citations:Array.isArray(data.citations)?data.citations:[],incomplete:!!data.incomplete,webSearchUsed:!!data.research?.webSearchUsed});
      session.draft='';question.value='';renderAnswers();message(data.incomplete?'Response received with an output limit. You can ask another follow-up.':'Research complete. Ask another question to explore further.');
    }catch(err){if(current===generation)message(err.name==='AbortError'?'Research timed out. Your question and evidence are preserved; try again.':err.message,true);}
    finally{clearTimeout(timer);if(current===generation){controller=null;busy(false);question.focus();}}
  });
  function enhance() {
    results.querySelectorAll('.card').forEach((card,i)=>{
      if(card.querySelector('.pending')||card.querySelector('.followup-trigger'))return;
      const heading=card.querySelector('h2');if(!heading)return;
      const button=document.createElement('button');button.type='button';button.className='act quiet followup-trigger';button.textContent='Ask a follow-up';button.setAttribute('aria-label','Ask a follow-up about '+heading.textContent);button.setAttribute('aria-haspopup','dialog');
      button.onclick=()=>{
        const key=card.id||'card-'+i;
        const title=heading.textContent,body=card.querySelector('.body')||card.querySelector('dl');
        if(!body)return;
        if(!sessions.has(key))sessions.set(key,{section:{title,text:body.innerText.slice(0,16000)},history:[],evidence:[],draft:''});
        active=sessions.get(key);active.section={title,text:body.innerText.slice(0,16000)};returnFocus=button;$('title').textContent=active.section.title;$('context').textContent=active.section.text;question.value=active.draft;renderFiles();renderAnswers();message('');busy(false);dialog.showModal();question.focus();
      };card.append(button);
    });
  }
  new MutationObserver(enhance).observe(results,{childList:true,subtree:true});
  window.SignalBriefFollowup={
    begin(value){if(dialog.open)close();stop();context=JSON.parse(JSON.stringify(value));sessions=new Map();active=null;},
    clear(){if(dialog.open)close();stop();context=null;sessions=new Map();active=null;}
  };
  enhance();
})();
