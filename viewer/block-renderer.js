/* Safe DOM renderer shared by the portable review page and the web consumer. */
(function(root,factory){if(typeof module==='object'&&module.exports)module.exports=factory();else root.PaessedBlocks=factory();})(typeof globalThis!=='undefined'?globalThis:this,function(){'use strict';

// Optional 0.2.0 prose convention. Never parse HTML or alter invalid markup.
function parseInlineText(text) {
 const tokens = [...text.matchAll(/<\/?[bi]>/g)];
 const stack = [];
 for (const token of tokens) {
  const tag = token[0][1] === '/' ? token[0][2] : token[0][1];
  if (token[0][1] === '/') {
   if (stack.pop() !== tag) return [{text, bold:false, italic:false}];
  } else stack.push(tag);
 }
 if (stack.length) return [{text, bold:false, italic:false}];
 const runs = []; let offset = 0; let bold = 0; let italic = 0;
 const add = value => { if (value) runs.push({text:value, bold:bold > 0, italic:italic > 0}); };
 for (const token of tokens) {
  add(text.slice(offset, token.index));
  const close = token[0][1] === '/'; const tag = close ? token[0][2] : token[0][1];
  if (tag === 'b') bold += close ? -1 : 1; else italic += close ? -1 : 1;
  offset = token.index + token[0].length;
 }
 add(text.slice(offset));
 return runs;
}
function plainText(text) { return parseInlineText(text).map(run => run.text).join(''); }
function appendInlineText(node, text, doc) {
 const runs = parseInlineText(text);
 if (!runs.some(run => run.bold || run.italic)) { node.textContent = plainText(text); return; }
 for (const run of runs) {
  const outer = doc.createElement(run.bold ? 'b' : run.italic ? 'i' : 'span');
  if (run.bold && run.italic) {
   const inner = doc.createElement('i'); inner.textContent = run.text; outer.append(inner);
  } else outer.textContent = run.text;
  node.append(outer);
 }
}

function renderBlocks(container,blocks,options={}) {
 const doc=container.ownerDocument; const fragment=doc.createDocumentFragment();
 function render(parent,list,depth){if(depth>16)throw new Error('Bloques demasiado anidados');
 for(const block of list||[]){const el=doc.createElement(block.type==='text'||(block.type==='math'&&!block.display)?'span':'div');el.className='paessed-block paessed-'+block.type;
 if(block.type==='text'){appendInlineText(el,block.text,doc);el.style.whiteSpace='pre-wrap';}
 else if(block.type==='math'){el.style.display=block.display?'block':'inline-block';try{if(!options.katex)throw new Error('KaTeX no disponible');options.katex.render(block.latex,el,{displayMode:block.display,throwOnError:true,trust:false,strict:'error',maxExpand:1000,maxSize:20,output:'htmlAndMathml'});}catch(error){el.setAttribute('role','alert');el.textContent='Fórmula pendiente de render: '+block.latex;el.classList.add('paessed-unresolved');if(options.onError)options.onError(error,block);}}
 else if(block.type==='image'){const url=options.assetUrls instanceof Map?options.assetUrls.get(block.asset_id):options.assetUrls?.[block.asset_id];if(url){const img=doc.createElement('img');img.src=url;img.alt=block.alt;img.style.maxWidth='100%';img.style.height='auto';el.append(img);}else{el.textContent='Recurso no disponible: '+block.asset_id;el.setAttribute('role','alert');}}
 else if(block.type==='table'){el.style.overflowX='auto';const table=doc.createElement('table');table.className='paessed-table';const tbody=doc.createElement('tbody');for(const row of block.rows){const tr=doc.createElement('tr');for(const cell of row){const td=doc.createElement('td');render(td,cell,depth+1);tr.append(td);}tbody.append(tr);}table.append(tbody);el.append(table);}
 else if(block.type==='unresolved'){el.setAttribute('role','status');el.textContent='Pendiente: '+block.reason;}
 else throw new Error('Bloque no soportado: '+block.type);
 parent.append(el);}}
 render(fragment,blocks,0);container.replaceChildren(fragment);return container;
}
return Object.freeze({renderBlocks,parseInlineText,plainText});});
