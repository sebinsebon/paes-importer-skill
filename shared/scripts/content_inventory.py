"""Source-observed requirements, kept outside model-editable final.json."""
import copy
import re
import unicodedata
from difflib import SequenceMatcher
from lab import bbox, blocks_in
from evidence import contains, cover_regions, rectangle_covered, overlaps


def with_solution_inventory(mapping, key_entry=None):
    """Combine frozen observations without copying or maintaining runtime code."""
    record = copy.deepcopy(mapping)
    inventory = record.setdefault('content_inventory', [])
    extra = (key_entry or {}).get('content_inventory', [])
    if not isinstance(inventory, list) or not isinstance(extra, list):
        raise ValueError('Observed content_inventory must be a list')
    for item in extra:
        if not isinstance(item, dict) or item.get('field') != 'explanation':
            raise ValueError('Solution inventory must contain explanation observations')
        source = (key_entry or {}).get('source_id')
        if not isinstance(source, str) or not source or item.get('source_id', source) != source:
            raise ValueError('Solution inventory must preserve its frozen source_id')
        inventory.append({**copy.deepcopy(item), 'source_id': source})
    return record


def _regions(regions, source, pages, message):
    if not isinstance(regions, list) or not regions:
        raise ValueError(message)
    for region in regions:
        if not isinstance(region, dict) or type(region.get('page')) is not int:
            raise ValueError('Inventory region must identify an integer physical page')
        page = pages.get((source, region['page']))
        if not page:
            raise ValueError('Inventory region outside source catalog')
        bbox(region.get('bbox'), page['width'], page['height'])


def _table_shapes(item):
    if 'shape' in item and 'shapes' in item:
        raise ValueError('Declare table shape or shapes, not both')
    if 'shape' in item:
        if item['count'] != 1:
            raise ValueError('Use shapes for multiple observed tables')
        return [item['shape']]
    return item.get('shapes', [])


def validate_inventory_record(record, catalog):
    inventory = record.get('content_inventory')
    if not isinstance(inventory, list):
        raise ValueError('Observe content_inventory explicitly (empty only for plain text)')
    labels = record.get('option_labels') or []
    pages = {(p['source_id'], p['page']): p for p in catalog['pages']}
    seen = set()
    for item in inventory:
        if not isinstance(item, dict):
            raise ValueError('Invalid content inventory entry')
        field, kind = item.get('field'), item.get('type')
        if field not in ['stem', 'explanation', *['options/' + label for label in labels]] or kind not in ('image', 'table', 'math'):
            raise ValueError('Inventory needs a stem/options/LABEL/explanation field and image/table/math type')
        source = item.get('source_id', record['source_id'])
        if not isinstance(source, str) or not source:
            raise ValueError('Inventory source_id must identify an observed source')
        if field != 'explanation' and source != record['source_id']:
            raise ValueError('Stem and option inventory must use the question source')
        if field == 'explanation' and not item.get('source_id'):
            raise ValueError('Explanation inventory requires its observed source_id')
        if (source, field, kind) in seen:
            raise ValueError('Duplicate inventory source/field/type; combine counts and regions')
        seen.add((source, field, kind))
        if type(item.get('count')) is not int or item['count'] < 1:
            raise ValueError('Inventory count must be a positive integer')
        _regions(item.get('regions'), source, pages, 'Inventory requires source regions including labels and units')
        allowed = record.get('source_fields', {}).get(field)
        if allowed and source == record['source_id'] and not cover_regions(item['regions'], allowed):
            raise ValueError('Inventory regions outside corresponding source_fields: ' + field)
        symbols = item.get('symbols', [])
        if not isinstance(symbols, list) or any(not isinstance(s, str) or not re.fullmatch('[A-Za-z]', s) for s in symbols):
            raise ValueError('Inventory symbols must be single mathematical variable letters')
        if symbols and kind != 'math':
            raise ValueError('Only math inventory entries declare variable symbols')
        exceptions = item.get('text_exceptions', [])
        if not isinstance(exceptions, list) or (exceptions and kind != 'math'):
            raise ValueError('Only math inventory entries declare text_exceptions')
        for exception in exceptions:
            if (not isinstance(exception, dict) or exception.get('symbol') not in symbols or
                    not isinstance(exception.get('reason'), str) or not exception['reason'].strip()):
                raise ValueError('text_exceptions require an observed symbol and reason')
            _regions(exception.get('regions'), source, pages, 'text_exceptions require localized source regions')
            if not cover_regions(item['regions'], exception['regions']) or not cover_regions(exception['regions'], item['regions']):
                raise ValueError('text_exceptions regions must cover the observed math regions without adding unrelated areas')
        representation = item.get('representation', 'editable')
        if representation not in ('editable', 'image-with-issue') or (representation != 'editable' and kind != 'table'):
            raise ValueError('Only tables support image-with-issue representation; math must remain editable')
        if kind == 'table':
            shapes = _table_shapes(item)
            if not isinstance(shapes, list) or (shapes and len(shapes) != item['count']):
                raise ValueError('Table shapes must follow each observed table in order')
            if record.get('source_fields') and representation == 'editable' and not shapes:
                raise ValueError('Observed editable tables require shape/shapes before transcription')
            for shape in shapes:
                if not isinstance(shape, dict) or any(type(shape.get(k)) is not int or shape[k] < 1 for k in ('rows', 'columns')):
                    raise ValueError('Table shape requires positive rows and columns')
                if 'headers' in shape and (not isinstance(shape['headers'], list) or len(shape['headers']) != shape['columns'] or
                        any(not isinstance(h, str) or not h.strip() for h in shape['headers'])):
                    raise ValueError('Observed table headers must match the column count')
            if representation == 'image-with-issue':
                limitation = item.get('limitation')
                if not isinstance(limitation, dict) or not isinstance(limitation.get('reason'), str) or not limitation['reason'].strip():
                    raise ValueError('Table image fallback needs a localized limitation reason')
                _regions(limitation.get('regions'), source, pages, 'Table image fallback needs limitation regions')
                if not cover_regions(item['regions'], limitation['regions']) or not cover_regions(limitation['regions'], item['regions']):
                    raise ValueError('Table limitation must cover its observed regions')


def _images_cover(question, item, blocks, record, candidate):
    assets = {a['id']: a for a in candidate['assets']}
    resources = [assets[b['asset_id']] for b in blocks if b['type'] == 'image' and b.get('asset_id') in assets]
    source = item.get('source_id', record.get('source_id', question['source_id']))
    allowed = record.get('source_fields', {}).get(item['field']) if source == record.get('source_id') else None
    for region in item['regions']:
        matching = [a for a in resources if a['source_id'] == source and a['page'] == region['page'] and contains(a['bbox'], region['bbox'])]
        if not matching:
            raise ValueError(question['id'] + ': CROP_EXCLUDES_SOURCE_REGION ' + item['field'])
        valid = []
        for asset in matching:
            field_boxes = [r['bbox'] for r in allowed or [] if r['page'] == asset['page']]
            if allowed and not rectangle_covered(asset['bbox'], field_boxes):
                continue
            # An option asset cannot also contain distinct essential neighboring
            # options, even when a mistakenly broad allowed box would permit it.
            invades = False
            if item['field'].startswith('options/'):
                for name, regions in record.get('source_fields', {}).items():
                    if name.startswith('options/') and name != item['field']:
                        for neighbor in regions:
                            if neighbor['page'] != asset['page'] or not overlaps(asset['bbox'], neighbor['bbox']):
                                continue
                            # Sharing is justified by BOTH frozen inventories,
                            # not by broad overlapping option bounding boxes.
                            other = [r for entry in record.get('content_inventory', [])
                                     if entry['field'] == name and entry.get('source_id', record['source_id']) == source
                                     and (entry['type'] == 'image' or entry.get('representation') == 'image-with-issue')
                                     for r in entry['regions'] if r['page'] == asset['page']]
                            shared = [r['bbox'] for r in item['regions'] if r['page'] == asset['page'] and
                                      any(contains(r['bbox'], other_region['bbox']) and contains(other_region['bbox'], r['bbox'])
                                          for other_region in other)]
                            intersection = [max(asset['bbox'][i], neighbor['bbox'][i]) if i < 2 else
                                            min(asset['bbox'][i], neighbor['bbox'][i]) for i in range(4)]
                            if not rectangle_covered(intersection, shared):
                                invades = True
            if not invades:
                valid.append(asset)
        if not valid:
            raise ValueError(question['id'] + ': CROP_OUTSIDE_FIELD_OR_NEIGHBOR ' + item['field'])


def validate_inventory(question, record, candidate):
    """Observed counts are minima; editable table dimensions are exact."""
    fields = {'stem': question['stem'], 'explanation': question.get('explanation', {}).get('blocks', []),
              **{'options/' + o['label']: o['blocks'] for o in question['options']}}
    for item in record.get('content_inventory', []):
        field_blocks = list(blocks_in(fields.get(item['field'], [])))
        if any(b['type'] == 'unresolved' for b in field_blocks):
            continue  # Explicit uncertainty remains partial, never complete.
        prefix = question['id'] + ': SOURCE_CONTENT_OMITTED ' + item['field']
        representation = item.get('representation', 'editable')
        if item['type'] == 'table' and representation == 'image-with-issue':
            if 'TABLE_STRUCTURE_IMAGE_FALLBACK' not in question.get('issues', []):
                raise ValueError(prefix + ': table image fallback needs TABLE_STRUCTURE_IMAGE_FALLBACK issue')
            images = [b for b in field_blocks if b['type'] == 'image']
            if len(images) < item['count']:
                raise ValueError(prefix + ' needs complete table image')
            _images_cover(question, item, images, record, candidate)
            continue
        blocks = [b for b in field_blocks if b['type'] == item['type']]
        if len(blocks) < item['count']:
            raise ValueError(prefix + ' needs ' + item['type'])
        if item['type'] == 'math':
            latex = ' '.join(b['latex'] for b in blocks)
            latex = re.sub(r'\\(?:text|textrm|textnormal|mathrm|operatorname)\s*\{[^{}]*\}', '', latex)
            variables = re.sub(r'\\[A-Za-z]+', '', latex)
            for symbol in item.get('symbols', []):
                if symbol not in variables:
                    raise ValueError(prefix + ': variable ' + symbol + ' needs math.latex')
                bare = any(bare_variable(b.get('text', ''), symbol) for b in field_blocks if b['type'] == 'text')
                exceptions = [e for e in item.get('text_exceptions', []) if e.get('symbol') == symbol and
                              e.get('reason', '').strip() and cover_regions(item['regions'], e.get('regions', []))]
                if bare and not exceptions:
                    raise ValueError(prefix + ': BARE_MATH_VARIABLE ' + symbol + ' requires math.latex or localized text_exceptions')
        if item['type'] == 'image':
            _images_cover(question, item, blocks, record, candidate)
        if item['type'] == 'table':
            for table, shape in zip(blocks, _table_shapes(item)):
                if len(table['rows']) != shape['rows'] or any(len(row) != shape['columns'] for row in table['rows']):
                    raise ValueError(prefix + ': TABLE_SHAPE_MISMATCH')
                if 'headers' in shape:
                    headers = [' '.join(b.get('text', b.get('latex', '')) for b in blocks_in(cell)).strip() for cell in table['rows'][0]]
                    normalize = lambda text: ' '.join(text.split())
                    if [normalize(h) for h in headers] != [normalize(h) for h in shape['headers']]:
                        raise ValueError(prefix + ': TABLE_HEADERS_MISMATCH')


def bare_variable(text, symbol):
    """Letters in Spanish prose are not, by themselves, evidence of mathematics.

    An isolated span or a letter next to an operator is still mathematical.
    Ambiguous prose is resolved by the source cotejo, never by rewriting it.
    """
    token = r'(?<!\w)' + re.escape(symbol) + r'(?!\w)'
    if not re.search(token, text):
        return False
    if symbol not in ('a', 'y', 'e', 'o', 'u') or text.strip() == symbol:
        return True
    return bool(re.search(token + r'\s*[=+*/^<>≤≥−]', text) or
                re.search(r'[=+*/^<>≤≥−]\s*' + token, text))


def math_text_candidates(text):
    """Localized review candidates; Spanish conjunctions and units stay prose.

    These are signals of omitted editable math, not a transcription or a solver.
    A lone variable-like letter without mathematical context is ambiguous.
    """
    patterns=[r'(?<!\w)[A-Za-z0-9]+\s*[=+*/^<>≤≥≠√]\s*[-−]?[A-Za-z0-9]+',
              r'(?i)\b(?:variable|incógnita|incognita|para todo|valor de)\s+[MNmnxy]\b',
              r'(?i)\b[MNmnxy]\s+(?:distinto|diferente|igual|mayor|menor)\b',
              r'(?<!\w)[A-Za-z0-9]+[²³⁴⁵⁶⁷⁸⁹₀₁₂₃₄₅₆₇₈₉]+(?!\w)',
              r'√\s*[A-Za-z0-9]+', r'(?<!\w)[A-Za-z]\s*[_^]\s*\{?\d+\}?']
    found=[]; seen=set()
    for pattern in patterns:
        for match in re.finditer(pattern,text):
            span=match.span()
            if span in seen: continue
            seen.add(span)
            found.append({'text':match.group(),'start':span[0],'end':span[1],
                          'code':'MATH_IN_PROSE_CANDIDATE','status':'pending'})
    for match in re.finditer(r'(?<!\w)[MNmnx](?!\w)',text):
        # A measurement/currency suffix is not evidence of a variable. Spanish
        # y/e/a/o/u remain excluded unless an explicit math context above fits.
        before=text[:match.start()]
        if re.search(r'(?:\d[\d.,]*|[$€])\s*$',before): continue
        if any(start<=match.start() and end>=match.end() for start,end in seen): continue
        found.append({'text':match.group(),'start':match.start(),'end':match.end(),
                      'code':'MATH_IN_PROSE_CANDIDATE','status':'pending'})
    return sorted(found,key=lambda item:item['start'])


def explanation_coverage(source_text, rendered_text):
    """Compare wording, keeping all differences subject to source observation."""
    def tokens(text):
        return re.findall(r'\w+|[=+*/^<>≤≥≠−-]',unicodedata.normalize('NFKC',text).casefold())
    source=tokens(source_text); result=tokens(rendered_text)
    if len(source)<5: return []
    matcher=SequenceMatcher(None,source,result,autojunk=False)
    covered=sum(block.size for block in matcher.get_matching_blocks())
    missing=[{'source_tokens':source[a:b],'source_token_range':[a,b]} for tag,a,b,_,_ in matcher.get_opcodes()
             if tag in ('delete','replace') and b>a]
    if not missing: return []
    return [{'code':'EXPLANATION_SOURCE_COVERAGE','status':'pending',
             'source_token_count':len(source),'matched_source_tokens':covered,
             'source_coverage':round(covered/len(source),4),'differences':missing,
             'action':'Compare the complete source development visually; preserve original wording and mathematics.'}]


def source_diagnostics(record, catalog, index=None, question=None, provenance=None):
    """Independent native signals; every result remains pending, never a verdict.

    Existing runs without native layout retain their explicit review contract.
    New catalogs supply layout so empty declared inventories cannot hide it.
    """
    pages={(p['source_id'],p['page']):p for p in (index or catalog).get('pages',[])}
    fields=record.get('source_fields',{})
    issues=[]; inventory=record.get('content_inventory',[])
    if not fields:
        issues.append({'code':'NATIVE_MAP_FIELDS_REQUIRED','status':'pending','field':'mapping',
                       'source_id':record['source_id'],
                       'action':'Localize stem and each option before interpreting native structure or declaring plain text.'})
    def add(code,field,region,**extra):
        issues.append({'code':code,'status':'pending','field':field,'source_id':record['source_id'],**region,**extra})
    for field,regions in fields.items():
        for region in regions:
            page=pages.get((record['source_id'],region['page']))
            if not page: continue
            rect=region['bbox']; full=[0,0,page['width'],page['height']]
            if contains(rect,full):
                add('SOURCE_FIELD_WHOLE_PAGE',field,region,
                    action='Delimit essential content or document a localized shared-region justification.')
            declared=[item for item in inventory if item['field']==field]
            native=[obj for obj in page.get('objects',[]) if contains(rect,obj['bbox']) and
                    obj['bbox'][2]-obj['bbox'][0]>=4 and obj['bbox'][3]-obj['bbox'][1]>=4]
            if native and not any(item['type'] in ('image','table') for item in declared):
                add('INVENTORY_NATIVE_STRUCTURE_UNDECLARED',field,region,object_ids=[o['id'] for o in native],
                    action='Observe these native objects; classify figure, table, decoration or background before approval.')
            for line in page.get('lines',[]):
                figure_label=any(item['type']=='image' and any(r['page']==region['page'] and contains(r['bbox'],line['bbox'])
                                  for r in item['regions']) for item in declared)
                if (not figure_label and overlaps(rect,line['bbox']) and math_text_candidates(line['text'])
                        and not any(item['type']=='math' for item in declared)):
                    add('INVENTORY_NATIVE_MATH_UNDECLARED',field,{'page':region['page'],'bbox':line['bbox']},text=line['text'])
            for hint in page.get('typography_hints',[])+page.get('repetition_hints',[]):
                if overlaps(rect,hint['bbox']):
                    issues.append({**hint,'field':field,'source_id':record['source_id'],'page':region['page']})
    # Cross-field sharing must carry its own reason and precise intersecting box.
    for i,(field,regions) in enumerate(fields.items()):
        for other,neighbors in list(fields.items())[i+1:]:
            for region in regions:
                for neighbor in neighbors:
                    if region['page']!=neighbor['page'] or not overlaps(region['bbox'],neighbor['bbox']): continue
                    intersection=[max(region['bbox'][0],neighbor['bbox'][0]),max(region['bbox'][1],neighbor['bbox'][1]),
                                  min(region['bbox'][2],neighbor['bbox'][2]),min(region['bbox'][3],neighbor['bbox'][3])]
                    justified=any(set(item.get('fields',[]))=={field,other} and item.get('reason','').strip() and
                                  cover_regions([{'page':region['page'],'bbox':intersection}],item.get('regions',[]))
                                  for item in record.get('shared_regions',[]))
                    if not justified:
                        add('SOURCE_FIELDS_OVERLAP_UNJUSTIFIED',field,{'page':region['page'],'bbox':intersection},other_field=other)
    if question:
        question_fields={'stem':question.get('stem',[]),
                         'explanation':question.get('explanation',{}).get('blocks',[]),
                         **{'options/'+o['label']:o['blocks'] for o in question.get('options',[])}}
        for field,blocks in question_fields.items():
            for position,block in enumerate(blocks_in(blocks)):
                if block['type']=='text':
                    for candidate in math_text_candidates(block.get('text','')):
                        issues.append({**candidate,'field':field,'block_position':position,'source_id':record['source_id']})
        # Use only actual observed solution regions, never the entire solution PDF.
        if index and provenance and provenance.get('origin')=='solution' and not provenance.get('regions'):
            issues.append({'code':'EXPLANATION_SOURCE_REGION_REQUIRED','status':'pending','field':'explanation',
                           'source_id':provenance.get('source_id'),'pages':provenance.get('pages',[provenance.get('page')]),
                           'action':'Localize the complete source development to compare wording without neighboring solutions.'})
        if index and provenance and provenance.get('regions'):
            from source_index import query_source_index
            source_id=provenance.get('source_id')
            if source_id in index.get('source_hashes',{}):
                native=query_source_index(index,source_id,regions=provenance['regions'],max_chars=None,layout='text')
                output=' '.join(b.get('text',b.get('latex','')) for b in blocks_in(question_fields['explanation']))
                for issue in explanation_coverage(native['text'],output):
                    issues.append({**issue,'field':'explanation','source_id':source_id,'regions':provenance['regions']})
    return issues
