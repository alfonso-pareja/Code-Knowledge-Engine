'use strict';
const $ = id => document.getElementById(id);
const element = (tag, text, cls='') => {const e=document.createElement(tag);e.textContent=text;e.className=cls;return e;};
async function fetchJson(url, options){
 const response=await fetch(url,options), body=await response.json();
 if(!response.ok)throw Error(body.error || `HTTP ${response.status}`);
 return body;
}
function switchTab(which){
 for(const tab of ['search','graph','config']){
  $(tab+'-panel').hidden=tab!==which;$( 'tab-'+tab).classList.toggle('active',tab===which);
 }
}
$('tab-search').onclick=()=>switchTab('search');$('tab-graph').onclick=()=>switchTab('graph');$('tab-config').onclick=()=>switchTab('config');
function options(){return {kb:$('kb').value,query:$('query').value.trim(),mode:$('mode').value,repos:$('repos').value,language:$('language').value.trim(),limit:Number($('limit').value)};}
function renderResults(results, output){
 output.replaceChildren();
 for(const row of results){
  const card=element('article','','panel');
  card.append(element('h3',row.symbol || row.filepath));
  card.append(element('p',`${row.source} / ${row.project} · ${row.filepath}:L${row.start_line}–${row.end_line}`,'meta'));
  card.append(element('p',`Snapshot: ${row.snapshot}`,'meta'));
  const score=row.rank_score ?? row.score ?? row.rank;
  if(score!=null)card.append(element('p',`Puntuación: ${Number(score).toFixed(6)}`,'meta'));
  const link=element('a','Abrir evidencia indexada');link.href='/api/source?'+new URLSearchParams({kb:row.kb,id:row.id});link.target='_blank';link.rel='noopener';card.append(link);
  if(row.citation)card.append(element('p',`[${row.citation}]`));
  card.append(element('pre',row.content));output.append(card);
 }
}
$('search-form').onsubmit=async event=>{
 event.preventDefault();$('search-status').textContent='Buscando…';
 try{const results=await fetchJson('/api/search?'+new URLSearchParams(options()));renderResults(results,$('results'));$('search-status').textContent=`${results.length} resultado(s)`;}
 catch(error){$('search-status').textContent=error.message;}
};
$('ask').onclick=async()=>{
 $('ask').disabled=true;$('answer-status').textContent='Generando respuesta…';$('answer').textContent='';$('citations').replaceChildren();
 try{const result=await fetchJson('/api/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...options(),model:$('model').value})});$('answer').textContent=result.handoff ? `${result.answer}\n\nPregunta: ${result.question}\n\n${result.context}\n\n${result.instructions.join('\n')}` : result.answer;renderResults(result.evidence,$('citations'));$('answer-status').textContent=result.handoff ? `Contexto preparado para ${result.handoff}; no se llamó a ningún modelo.` : result.grounded?'Citas vinculadas a evidencia; verifica las conclusiones.':'Evidencia insuficiente o citas no válidas.';}
 catch(error){$('answer-status').textContent=error.message;}
 finally{$('ask').disabled=false;}
};
function drawGraph(graph){
 const svg=$('graph');svg.replaceChildren();const ns='http://www.w3.org/2000/svg';
 const nodes=graph.nodes.slice(0,60),positions=new Map();
 nodes.forEach((node,i)=>{const angle=2*Math.PI*i/Math.max(nodes.length,1);positions.set(node.id,{x:500+410*Math.cos(angle),y:250+200*Math.sin(angle)});});
 for(const edge of graph.edges){const a=positions.get(edge.source),b=positions.get(edge.target);if(!a||!b)continue;const line=document.createElementNS(ns,'line');for(const [k,v] of Object.entries({x1:a.x,y1:a.y,x2:b.x,y2:b.y}))line.setAttribute(k,v);svg.append(line);}
 for(const node of nodes){const p=positions.get(node.id),group=document.createElementNS(ns,'g'),circle=document.createElementNS(ns,'circle');circle.setAttribute('cx',p.x);circle.setAttribute('cy',p.y);circle.setAttribute('r',7);const title=document.createElementNS(ns,'title');title.textContent=`${node.source || 'externo'} ${node.filepath}`;circle.append(title);group.append(circle);const label=document.createElementNS(ns,'text');label.setAttribute('x',p.x+9);label.setAttribute('y',p.y);label.textContent=node.filepath.split('/').pop().slice(0,22);group.append(label);group.setAttribute('tabindex','0');group.setAttribute('role','button');group.setAttribute('aria-label',node.filepath);const select=()=>{$('graph-results').replaceChildren(element('p',`${node.source || 'externo'} / ${node.project || ''} / ${node.filepath}`));if(node.chunk_id){const link=element('a','Abrir evidencia');link.href='/api/source?'+new URLSearchParams({kb:$('graph-kb').value,id:node.chunk_id});link.target='_blank';link.rel='noopener';$('graph-results').append(link);}};group.onclick=select;group.onkeydown=e=>{if(e.key==='Enter')select();};svg.append(group);}
 return nodes.length;
}
$('graph-form').onsubmit=async event=>{
 event.preventDefault();$('graph-status').textContent='Cargando…';
 try{const graph=await fetchJson('/api/network?'+new URLSearchParams({kb:$('graph-kb').value}));const shown=drawGraph(graph);$('graph-status').textContent=`${shown}/${graph.nodes.length} nodos · ${graph.edges.length} relaciones. ${graph.warning}`;}
 catch(error){$('graph-status').textContent=error.message;}
};
fetchJson('/api/kbs').then(kbs=>{for(const id of ['kb','graph-kb'])for(const kb of kbs){const option=element('option',kb);option.value=kb;$(id).append(option);}}).catch(error=>{$('search-status').textContent=error.message;});

function applyConfiguration(config){
 $('provider').value=config.provider;$('answer-model').value=config.model;
 $('embedding-provider').value=config.embedding_provider;$('embedding-model').value=config.embedding_model;
 $('allow-cloud-code').checked=config.allow_cloud_code;$('model').value='';
 $('model').placeholder=config.model || 'El modelo se elige en el agente';
 $('mode').value=config.search_mode;
 for(const option of $('mode').options)option.disabled=config.embedding_provider==='none' && option.value!=='keyword';
 $('ask').textContent=['copilot','chatgpt','codex'].includes(config.provider)?'Preparar contexto para el agente':'Generar respuesta';
 $('config-help').textContent=config.instructions.join('\n')+`\n\nOPENAI_API_KEY: ${config.api_key_configured?'configurada':'no configurada'}`;
}
$('provider').onchange=()=>{
 const provider=$('provider').value,local=provider==='ollama',cloud=provider==='openai';
 $('answer-model').value=local?'llama3.2':cloud?'gpt-4.1-mini':'';
 $('embedding-provider').value=local?'ollama':cloud?'openai':'none';
 $('embedding-model').value=local?'embeddinggemma':cloud?'text-embedding-3-small':'';
 $('allow-cloud-code').checked=false;
};
$('embedding-provider').onchange=()=>{$('embedding-model').value=({ollama:'embeddinggemma',openai:'text-embedding-3-small',none:''})[$('embedding-provider').value];};
$('config-form').onsubmit=async event=>{
 event.preventDefault();$('config-status').textContent='Guardando…';
 const settings={provider:$('provider').value,embedding_provider:$('embedding-provider').value,allow_cloud_code:$('allow-cloud-code').checked};
 if($('answer-model').value.trim())settings.model=$('answer-model').value.trim();
 if($('embedding-model').value.trim())settings.embedding_model=$('embedding-model').value.trim();
 try{const config=await fetchJson('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(settings)});applyConfiguration(config);$('config-status').textContent='Configuración guardada. Revisa las instrucciones antes de usar el proveedor.';}
 catch(error){$('config-status').textContent=error.message;}
};
fetchJson('/api/config').then(applyConfiguration).catch(error=>{$('config-status').textContent=error.message;});
