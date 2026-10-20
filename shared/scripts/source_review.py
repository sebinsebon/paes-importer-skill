"""Create a private source/result inspection page; no certification is performed."""
import hashlib
import io
import json
import math
import shutil
import sys
import zipfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'shared/scripts'))
from lab import configure_workspace, artifact_path, bbox, no_links
from package_io import validate, inspect_package
from pdf_assets import render_crop
from runtime_environment import external_directory, external_path
import pypdfium2 as pdfium

def digest_bytes(blob):
    return hashlib.sha256(blob).hexdigest()

def asset_blobs(candidate, data, payload):
    candidate = Path(candidate)
    if candidate.suffix.lower() in ('.zip', '.paessed'):
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            return {r['path']: archive.read(r['path']) for r in data['assets'] + data['evidence']}
    return {r['path']: artifact_path(candidate.parent, r['path']).read_bytes() for r in data['assets'] + data['evidence']}

HTML = r'''<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Inspección de fuente y resultado PAESSED</title>
<link rel="stylesheet" href="vendor/katex/dist/katex.min.css"><link rel="stylesheet" href="block-renderer.css">
<style>body{margin:0;background:#f3f4f6;color:#17212b;font:16px system-ui,sans-serif}header{padding:1.5rem;background:#17212b;color:white}main{max-width:1500px;margin:auto;padding:1rem}.question{background:white;border:1px solid #cbd5e1;border-radius:8px;padding:1rem;margin-bottom:1.5rem}.compare{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:1.5rem}.source-page{position:relative;border:1px solid #cbd5e1;margin:.5rem 0}.source-page img{display:block;width:100%;height:auto}.region{position:absolute;border:2px solid #d97706;box-sizing:border-box;pointer-events:none;background:#fbbf2415}.region.asset{border-color:#dc2626;background:#dc262611}.region.required{border-color:#2563eb;background:#2563eb11}.crop img{max-width:100%;height:auto;border:1px solid #dc2626}.crop{margin:1rem 0}.meta{color:#475569;overflow-wrap:anywhere;font-size:.85rem}.option{display:grid;grid-template-columns:2rem minmax(0,1fr);margin:.75rem 0}.pending{color:#9a3412;background:#ffedd5;padding:.6rem}.result{overflow-wrap:anywhere}h2,h3{margin:.8rem 0}a{color:#0369a1}.paessed-table{border-collapse:collapse}.paessed-table td{border:1px solid #94a3b8;padding:.5rem}@media(max-width:850px){.compare{grid-template-columns:1fr}}@media print{header{background:white;color:black}.question{break-inside:avoid}.compare{gap:.5rem}}</style></head>
<body><header><h1>Fuente y resultado</h1><p>Inspector privado. Revisión visual, matemática e independiente pendientes; esta página no certifica contenido.</p><p id="identity"></p><div id="errors" role="alert"></div></header><main id="questions"></main>
<script id="review-data" type="application/json">__DATA__</script>
<script src="vendor/katex/dist/katex.min.js"></script><script src="block-renderer.js"></script>
<script>
'use strict';
const review=JSON.parse(document.getElementById('review-data').textContent);
const data=review.candidate, sourceMap=new Map(data.sources.map(s=>[s.id,s]));
const pageMap=new Map(review.pages.map(p=>[JSON.stringify([p.source_id,p.page]),p]));
const assets=Object.fromEntries(data.assets.map(a=>[a.id,a.path]));
const identity=document.getElementById('identity');identity.textContent=data.exam.title+' · '+data.questions.length+' preguntas · SHA-256 '+review.candidate_sha256;
function el(tag,text,parent){const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(parent)parent.append(node);return node;}
function render(parent,blocks){PaessedBlocks.renderBlocks(parent,blocks,{assetUrls:assets,katex:window.katex,onError(error){el('p','Error KaTeX: '+error.message,document.getElementById('errors'));}});}
for(const q of data.questions){
 const section=el('section',undefined,document.getElementById('questions'));section.className='question';section.id='question-'+q.id;section.dataset.questionId=q.id;
 el('h2','Pregunta '+q.number+' · '+q.id,section);
 const meta=el('p','Fidelidad declarada: '+q.fidelity.status+' · Respuesta: '+(q.answer.label===null?'pendiente':q.answer.label)+' ('+q.answer.status+')',section);meta.className='meta';
 if(q.curriculum)el('p','Currículo: '+(q.curriculum.eje??'pendiente')+' / '+(q.curriculum.subeje??'pendiente')+' / '+q.curriculum.en_temario,section).className='meta';
 if(q.issues.length)el('p','Incidencias: '+q.issues.join('; '),section).className='pending';
 const compare=el('div',undefined,section);compare.className='compare';const source=el('div',undefined,compare),result=el('div',undefined,compare);result.className='result';
 const usedIds=new Set();function collect(blocks){for(const b of blocks){if(b.type==='image')usedIds.add(b.asset_id);if(b.type==='table')for(const row of b.rows)for(const cell of row)collect(cell);}}
 collect(q.stem);for(const o of q.options)collect(o.blocks);collect(q.explanation.blocks);const usedAssets=data.assets.filter(a=>usedIds.has(a.id));
 el('h3','Fuente PDF',source);el('p','Naranja: pregunta. Rojo: recorte solicitado. Azul: contenido observado que debe conservarse.',source).className='meta';
 for(const context of review.question_pages[q.id]){const p=pageMap.get(JSON.stringify([context.source_id,context.page]));el('p',sourceMap.get(p.source_id).name+' · página física '+p.page,source).className='meta';
  const frame=el('div',undefined,source);frame.className='source-page';const image=el('img',undefined,frame);image.src=p.path;image.alt='Página '+p.page+' de '+sourceMap.get(p.source_id).name;
  function outline(r,kind,label){const region=el('div',undefined,frame);region.className='region '+kind;region.title=label;region.style.left=(100*r.bbox[0]/p.width)+'%';region.style.top=(100*r.bbox[1]/p.height)+'%';region.style.width=(100*(r.bbox[2]-r.bbox[0])/p.width)+'%';region.style.height=(100*(r.bbox[3]-r.bbox[1])/p.height)+'%';}
  for(const r of q.regions.filter(r=>q.source_id===p.source_id&&r.page===p.page))outline(r,'','Pregunta');
  for(const a of usedAssets.filter(a=>a.source_id===p.source_id&&a.page===p.page))outline(a,'asset',a.id);
  for(const item of review.requirements[q.id]||[])for(const r of item.regions.filter(r=>(item.source_id||q.source_id)===p.source_id&&r.page===p.page))outline(r,'required',item.field+' / '+item.type);
 }
 el('h3','Contenido importado',result);render(el('div',undefined,result),q.stem);
 for(const option of q.options){const row=el('div',undefined,result);row.className='option';el('strong',option.label,row);render(el('div',undefined,row),option.blocks);}
 el('h3','Explicación',result);render(el('div',undefined,result),q.explanation.blocks);
 if(usedAssets.length)el('h3','Recortes: comprobar figuras completas y contenido vecino',result);
 for(const a of usedAssets){const crop=el('div',undefined,result);crop.className='crop';el('p',a.id+' / '+a.source_id+' p.'+a.page+' / '+JSON.stringify(a.bbox),crop).className='meta';const img=el('img',undefined,crop);img.src=a.path;img.alt=a.id;}
}
window.__PAES_REVIEW_READY__=true;
</script></body></html>'''

def safe_output(output, workspace=None):
    if workspace is None:
        raise ValueError('Supply an explicit external workspace for review output')
    output = external_path(output)
    boundary = external_directory(workspace)
    if output == boundary or not output.is_relative_to(boundary):
        raise ValueError('Review outputs must be a fresh directory within the selected workspace')
    if output.exists():
        raise ValueError('Preserve existing review; select a fresh directory')
    return output


def build_review(candidate, sources, output, scale=1.5, *, workspace=None, context=None, requirements=None):
    if not isinstance(scale, (int,float)) or not math.isfinite(scale) or not .25 <= scale <= 3:
        raise ValueError('Scale must be between .25 and 3')
    output = safe_output(output, workspace)
    candidate_payload = Path(candidate).read_bytes()
    if Path(candidate).suffix.lower() in ('.zip', '.paessed'):
        inspect_package(candidate)
        with zipfile.ZipFile(io.BytesIO(candidate_payload)) as archive:
            data = json.loads(archive.read('final.json'))
    else:
        data = json.loads(candidate_payload.decode('utf-8-sig'))
    blobs = asset_blobs(candidate, data, candidate_payload)
    validate(data, blob_reader=blobs.__getitem__)
    declared = {s['id']:s for s in data['sources']}
    if set(sources) != set(declared):
        raise ValueError('Supply every declared source exactly once by ID')
    geometry = {}
    source_payloads = {}
    for sid, source in declared.items():
        file = Path(sources[sid])
        payload = file.read_bytes()
        if digest_bytes(payload) != source['sha256']:
            raise ValueError('Source PDF hash mismatch: '+sid)
        source_payloads[sid] = payload
        with pdfium.PdfDocument(payload) as document:
            if len(document) != source['page_count']:
                raise ValueError('Source page count mismatch: '+sid)
            for index in range(len(document)):
                page = document[index]
                try: geometry[(sid,index+1)] = tuple(map(float,page.get_size()))
                finally: page.close()
    for resource in data['assets']+data['evidence']:
        width,height = geometry[(resource['source_id'],resource['page'])]
        bbox(resource['bbox'],width,height)
    assets = {a['id']:a for a in data['assets']}
    from lab import question_blocks
    question_pages = {}
    needed = set()
    for q in data['questions']:
        pages = {(q['source_id'],r['page']) for r in q['regions']}
        for r in q['regions']:
            width,height=geometry[(q['source_id'],r['page'])]
            bbox(r['bbox'],width,height)
        if not pages:
            pages = {(q['source_id'],p) for p in range(1,declared[q['source_id']]['page_count']+1)}
        pages.update((assets[b['asset_id']]['source_id'],assets[b['asset_id']]['page']) for b in question_blocks(q) if b['type']=='image')
        pages.update((p['source_id'], p['page']) for p in (context or {}).get(q['id'], []))
        if not pages.issubset(geometry):
            raise ValueError('Review context outside declared source pages')
        needed.update(pages)
        question_pages[q['id']] = [{'source_id':sid,'page':page} for sid,page in sorted(pages)]
    # All content and source preflight precedes creation of the private output.
    output.mkdir(parents=True)
    configure_workspace(output)
    used_paths = {assets[b['asset_id']]['path'] for q in data['questions'] for b in question_blocks(q) if b['type']=='image'}
    for name,blob in blobs.items():
        if name in used_paths:
            destination=artifact_path(output,name);destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(blob)
    shutil.copyfile(ROOT/'viewer/block-renderer.js',output/'block-renderer.js')
    shutil.copyfile(ROOT/'viewer/block-renderer.css',output/'block-renderer.css')
    shutil.copytree(ROOT/'viewer/vendor/katex',output/'vendor/katex')
    pages = []
    ordinals = {sid:i+1 for i,sid in enumerate(sorted(declared))}
    for sid in sorted(declared):
        with pdfium.PdfDocument(source_payloads[sid]) as document:
            for source_id, page_no in sorted(p for p in needed if p[0]==sid):
                name=f'pages/source-{ordinals[sid]:04d}-p{page_no:04d}.png'
                page=document[page_no-1]
                try:render_crop(page,output/name,scale=scale)
                finally:page.close()
                width,height=geometry[(sid,page_no)]
                pages.append({'source_id':sid,'page':page_no,'width':width,'height':height,'path':name,'sha256':digest_bytes((output/name).read_bytes())})
    report={'candidate':data,'candidate_sha256':digest_bytes(candidate_payload),'pages':pages,
        'question_pages':question_pages,'requirements':requirements or {},'review_status':'pending','certification':'not_performed'}
    encoded=json.dumps(report,ensure_ascii=False).replace('&',r'\u0026').replace('<',r'\u003c').replace('>',r'\u003e')
    (output/'index.html').write_text(HTML.replace('__DATA__',encoded),encoding='utf-8')
    inventory={k:v for k,v in report.items() if k!='candidate'}
    inventory['sources']=[{'id':sid,'sha256':source['sha256'],'name':source['name']} for sid,source in declared.items()]
    (output/'review-inventory.json').write_text(json.dumps(inventory,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return {'html':str(output/'index.html'),'pages_rendered':len(pages),'questions':len(data['questions']),
            'certification':'not_performed','review_status':'pending'}
