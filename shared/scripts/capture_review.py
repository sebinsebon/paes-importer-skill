"""Optional screenshots of an existing source/result snapshot; never an approval."""
import importlib
import os
import struct
import time
import mimetypes
from pathlib import Path
from urllib.parse import urlparse, unquote
from urllib.request import url2pathname

from lab import artifact_path, digest, inside, read, write
from runtime_environment import RUNTIME_ROOT, external_directory, process_environment

PROTOCOL = 'review-capture-1'


def _load_playwright():
    # Optional dependency: importing this module or the minimal runtime never loads it.
    return importlib.import_module('playwright.sync_api').sync_playwright


def _png_size(path):
    with Path(path).open('rb') as stream:
        header = stream.read(24)
    if len(header) != 24 or header[:8] != b'\x89PNG\r\n\x1a\n' or header[12:16] != b'IHDR':
        raise ValueError('Capture is not a PNG image')
    size = struct.unpack('>II', header[16:24])
    if min(size) < 1:
        raise ValueError('Capture has empty dimensions')
    # A header alone is not a visual artifact. Decode all pixels before a
    # screenshot (including an attributed external screenshot) can be cited.
    from PIL import Image
    try:
        with Image.open(path) as image:
            if image.format != 'PNG' or image.size != size:
                raise ValueError('Capture is not a consistent PNG image')
            image.load()
    except (OSError, SyntaxError) as error:
        raise ValueError('Capture PNG cannot be decoded') from error
    return list(size)


def _local_request_allowed(url, snapshot):
    parsed = urlparse(url)
    if parsed.scheme != 'file' or parsed.netloc not in ('', 'localhost'):
        return False
    path = Path(url2pathname(parsed.path)).resolve()
    return path.is_relative_to(snapshot) and path.is_file()


def memory_request(route, snapshot):
    """Serve the same snapshot bytes in memory; no request reaches the network."""
    parsed = urlparse(route.request.url)
    try:
        if parsed.scheme != 'https' or parsed.netloc != 'paes-review.invalid':
            raise ValueError('External review request')
        path = artifact_path(snapshot, unquote(parsed.path).lstrip('/'))
        if not path.is_file():
            raise ValueError('Missing snapshot resource')
        route.fulfill(status=200, body=path.read_bytes(),
                      content_type=mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
    except (ValueError, OSError):
        route.abort()


def capture_review(folder, reference, *, executable_path=None, transport='auto', question_ids=None,
                   pending=False, resume_receipt=None):
    """Capture a current snapshot into a fresh run directory; preserve failures."""
    from visual_review import validate_review, select_questions
    if transport not in ('auto', 'file', 'memory'):
        raise ValueError('Capture transport must be auto, file or memory')
    folder = external_directory(folder)
    candidate = read(folder/'candidate.json')
    review_record = read(artifact_path(folder, reference['path'], 'reviews'))
    selected = select_questions(candidate, question_ids if question_ids is not None else list(review_record['questions']))
    cache = {}
    for question in selected:
        validate_review(folder, reference, question, candidate, cache)
    snapshot = artifact_path(folder, reference['path'], 'reviews').parent
    if pending and resume_receipt is None:
        matches = []
        wanted = {q['id'] for q in selected}
        for path in (folder/'reviews').glob('capture-*/capture-manifest.json'):
            receipt = {'path':path.relative_to(folder).as_posix(), 'sha256':digest(path)}
            try:
                previous = validate_capture(folder, receipt, reference, None, cache=cache, allow_partial=True)
                coverage = len(wanted & {s['question_id'] for s in previous['screenshots']})
                matches.append((coverage, path.stat().st_mtime_ns, receipt))
            except (ValueError, OSError, KeyError, TypeError):
                continue
        if matches:
            resume_receipt = max(matches, key=lambda match:match[:2])[2]
    if executable_path is not None:
        # Reading an existing system browser may legitimately follow /usr/bin links.
        # Browser profiles and generated files still use validated external paths.
        executable_path = Path(executable_path).expanduser().resolve(strict=True)
        if not executable_path.is_file() or executable_path.is_relative_to(RUNTIME_ROOT):
            raise ValueError('Explicit browser executable does not exist')
    if resume_receipt is not None:
        manifest = validate_capture(folder, resume_receipt, reference, None, allow_partial=True)
        if manifest.get('run_id') != candidate['run']['id']:
            raise ValueError('Capture belongs to another run')
        output = artifact_path(folder, resume_receipt['path'], 'reviews').parent
    else:
        output = inside(folder/'reviews'/('capture-' + str(time.time_ns())))
        external_directory(output)
        if output.exists():
            raise ValueError('Select a fresh capture directory')
        output.mkdir(parents=True)
        manifest = {'protocol': PROTOCOL, 'status': 'running', 'render_review': reference,
                    'run_id': candidate['run']['id'], 'screenshots': [],
                    'review_status': 'pending', 'certification': 'not_performed'}
    done = {item['question_id'] for item in manifest['screenshots']}
    selected = [q for q in selected if q['id'] not in done]
    manifest_path = output/'capture-manifest.json'
    if not selected and resume_receipt is not None:
        return {**manifest, 'capture_receipt': {'path':manifest_path.relative_to(folder).as_posix(),
                                               'sha256':digest(manifest_path)}, 'reused': sorted(done)}
    if resume_receipt is not None:
        # Receipts already cited by accepted cotejos are immutable. A resumed
        # operation gets a new manifest and copies only verified visual bytes.
        import copy
        import shutil
        previous_output = output
        output = inside(folder/'reviews'/('capture-' + str(time.time_ns())))
        external_directory(output); output.mkdir(parents=True, exist_ok=False)
        manifest = copy.deepcopy(manifest)
        for item in manifest['screenshots'] + ([manifest['capability_probe']] if manifest.get('capability_probe') else []):
            source = artifact_path(folder, item['path'], 'reviews')
            image = output/source.name
            shutil.copy2(source, image)
            item['path'] = image.relative_to(folder).as_posix()
        manifest['resumed_from'] = resume_receipt
        manifest_path = output/'capture-manifest.json'
    manifest.update(status='running', requested_question_ids=[q['id'] for q in selected])
    write(manifest_path, manifest)
    previous_environment = dict(os.environ)
    try:
        factory = _load_playwright()
        env = process_environment(output, create=True)
        os.environ.update(env)
        with factory() as playwright:
            launch = {'headless': True, 'env': env}
            if executable_path is not None:
                launch['executable_path'] = str(executable_path)
            browser = playwright.chromium.launch(**launch)
            try:
                context = browser.new_context(viewport={'width': 1440, 'height': 1000},
                                              device_scale_factor=1, service_workers='block')
                context.route('**/*', lambda route: route.continue_()
                              if _local_request_allowed(route.request.url, snapshot) else route.abort())
                page = context.new_page()
                errors = []
                if hasattr(page, 'on'):
                    page.on('pageerror', lambda error: errors.append(str(error)))
                def load_memory():
                    context.unroute('**/*')
                    context.route('**/*', lambda route: memory_request(route, snapshot))
                    html = (snapshot/'index.html').read_text(encoding='utf-8')
                    html = html.replace('<head>', '<head><base href="https://paes-review.invalid/">', 1)
                    page.set_content(html, wait_until='load', timeout=30000)
                    manifest['transport'] = 'memory'
                def can_retry_memory(error):
                    return transport == 'auto' and manifest.get('transport', 'file') == 'file' and any(
                        code in str(error) or code in type(error).__name__ for code in (
                            'ERR_BLOCKED_BY_ADMINISTRATOR', 'ERR_ACCESS_DENIED',
                            'Not allowed to load local resource', 'Timeout', 'Image load failed',
                            'Image not rendered', 'ERR_FILE_NOT_FOUND'))
                def ensure_rendered():
                    page.wait_for_function('window.__PAES_REVIEW_READY__ === true', timeout=30000)
                    page.evaluate('''async () => {
                        await document.fonts.ready;
                        await Promise.all(Array.from(document.images, img => img.complete ? Promise.resolve() :
                            new Promise((resolve,reject) => {img.onload=resolve;img.onerror=()=>reject(new Error('Image load failed'));})));
                        if (Array.from(document.images).some(img => !img.naturalWidth)) throw new Error('Image not rendered');
                    }''')
                if transport == 'memory':
                    load_memory()
                else:
                    # The attempt starts with file navigation even when its
                    # immutable predecessor was captured through memory.
                    manifest['transport'] = 'file'
                    try:
                        page.goto((snapshot/'index.html').as_uri(), wait_until='load', timeout=30000)
                        manifest['transport'] = 'file'
                    except Exception as error:
                        if not can_retry_memory(error):
                            raise
                        manifest['file_limitation'] = str(error)
                        load_memory()
                try:
                    ensure_rendered()
                except Exception as error:
                    if not can_retry_memory(error):
                        raise
                    manifest['file_limitation'] = str(error)
                    errors.clear()
                    load_memory()
                    ensure_rendered()
                if page.locator('#errors').inner_text().strip():
                    raise ValueError('Rendered review reports mathematical or content errors')
                if errors:
                    raise ValueError('Rendered review reports JavaScript errors: ' + '; '.join(errors))
                probe = page.evaluate('''() => {
                    const node=document.getElementById('capture-self-test');
                    return !!(node && node.getBoundingClientRect().width > 0 &&
                        node.textContent.includes('texto PAES') && node.querySelector('.katex') &&
                        node.querySelector('table td') && node.querySelector('img').naturalWidth > 0);
                }''')
                if probe is not True:
                    raise ValueError('Observable text/math/table/image capture self-test failed')
                probe_image = output/'capability-probe.png'
                page.locator('#capture-self-test').screenshot(path=str(probe_image), animations='disabled', caret='hide', timeout=30000)
                manifest['capability_probe'] = {'path':probe_image.relative_to(folder).as_posix(),
                    'sha256':digest(probe_image), 'size':_png_size(probe_image),
                    'components':['text','math','table','image']}
                sections = page.locator('section.question')
                ids = sections.evaluate_all('(nodes) => nodes.map(node => node.dataset.questionId)')
                if ids != list(review_record['questions']):
                    raise ValueError('Rendered question inventory differs from snapshot')
                for question in selected:
                    index = ids.index(question['id'])
                    image = output/('question-' + str(index+1).zfill(5) + '.png')
                    sections.nth(index).screenshot(path=str(image), animations='disabled', caret='hide', timeout=30000)
                    manifest['screenshots'].append({'question_id': question['id'],
                        'path': image.relative_to(folder).as_posix(), 'sha256': digest(image),
                        'size': _png_size(image)})
                    write(manifest_path, manifest)
                manifest['browser'] = {'engine': 'chromium', 'version': browser.version,
                                       'source': 'explicit-executable' if executable_path else 'external-managed-cache'}
                manifest['status'] = 'captured'
            finally:
                browser.close()
    except Exception as error:
        # No install/download attempt is made. Keep any images already produced for diagnosis.
        manifest.update(status='partial' if manifest['screenshots'] else 'unavailable',
                        limitation=type(error).__name__ + ': ' + str(error))
    finally:
        os.environ.clear()
        os.environ.update(previous_environment)
        write(manifest_path, manifest)
    return {**manifest, 'capture_receipt': {'path': manifest_path.relative_to(folder).as_posix(),
                                           'sha256': digest(manifest_path)},
            'next': 'Inspect the screenshots and record the observation; capture generation does not perform visual review.'
                    if manifest['status'] == 'captured' else
                    'Use native HTML inspection or an explicitly installed optional capture tool. Visual review remains pending.'}


def validate_capture(folder, receipt, reference, question_id, cache=None, allow_partial=False):
    if not isinstance(receipt, dict) or set(receipt) != {'path', 'sha256'}:
        raise ValueError('Image observation needs its capture_receipt')
    path = artifact_path(folder, receipt['path'], 'reviews')
    cache = cache if cache is not None else {}
    cache_key = ('capture', receipt['path'], receipt['sha256'], str(reference), allow_partial)
    if cache_key in cache:
        record = cache[cache_key]
        if question_id is not None and question_id not in {s['question_id'] for s in record['screenshots']}:
            raise ValueError('Capture does not include this question')
        return record
    if not path.is_file() or digest(path) != receipt['sha256']:
        raise ValueError('Altered capture receipt')
    record = read(path)
    allowed = ('captured', 'partial', 'running', 'unavailable') if allow_partial else ('captured', 'partial')
    if record.get('protocol') != PROTOCOL or record.get('status') not in allowed or record.get('render_review') != reference:
        raise ValueError('Capture receipt is incomplete or belongs to another render review')
    screenshots = record.get('screenshots')
    if not isinstance(screenshots, list) or (not screenshots and not allow_partial):
        raise ValueError('Capture receipt has no screenshots')
    seen = set()
    for item in screenshots:
        qid = item.get('question_id')
        if not isinstance(qid, str) or qid in seen:
            raise ValueError('Capture receipt has duplicate or invalid questions')
        seen.add(qid)
        image = artifact_path(folder, item['path'], 'reviews')
        if image.parent != path.parent or not image.is_file() or digest(image) != item['sha256']:
            raise ValueError('Altered screenshot or image outside capture directory')
        if _png_size(image) != item.get('size'):
            raise ValueError('Capture dimensions differ from receipt')
    probe = record.get('capability_probe')
    if screenshots and record.get('origin') != 'attributed-browser-artifact':
        if not isinstance(probe, dict) or probe.get('components') != ['text','math','table','image']:
            raise ValueError('Capture needs its observable capability probe')
        image = artifact_path(folder, probe['path'], 'reviews')
        if image.parent != path.parent or not image.is_file() or digest(image) != probe['sha256'] or _png_size(image) != probe['size']:
            raise ValueError('Altered capture capability probe')
    if question_id is not None and question_id not in seen:
        raise ValueError('Capture does not include this question')
    cache[cache_key] = record
    return record


def record_browser_capture(folder, reference, question_id, image_path, *, tool, observation):
    """Archive an attributed browser screenshot; existence is not comprehension."""
    import shutil
    from visual_review import validate_review, select_questions
    folder = external_directory(folder)
    candidate = read(folder/'candidate.json')
    question = select_questions(candidate, [question_id])[0]
    validate_review(folder, reference, question, candidate)
    if any(not isinstance(value, str) or not value.strip() for value in (tool, observation)):
        raise ValueError('Browser artifact needs attribution and a concrete observation')
    source = Path(image_path).expanduser().resolve(strict=True)
    size = _png_size(source)
    output = inside(folder/'reviews'/('browser-capture-' + str(time.time_ns())))
    external_directory(output); output.mkdir(parents=True)
    image = output/'question.png'; shutil.copyfile(source, image)
    record = {'protocol':PROTOCOL, 'status':'captured', 'render_review':reference,
        'run_id':candidate['run']['id'], 'origin':'attributed-browser-artifact', 'tool':tool,
        'observation':observation, 'review_status':'pending', 'certification':'not_performed',
        'screenshots':[{'question_id':question_id,'path':image.relative_to(folder).as_posix(),
                        'sha256':digest(image),'size':size}]}
    manifest = output/'capture-manifest.json'; write(manifest, record)
    return {'path':manifest.relative_to(folder).as_posix(), 'sha256':digest(manifest)}


def startup_probe(folder, *, executable_path=None, transport='auto'):
    """Observe a tiny current-renderer sample without asserting source fidelity.

    The archived image must still be inspected by the host. Missing optional
    browser support is a functional unavailable result, never a false pass.
    """
    import json
    import shutil
    from source_review import HTML
    from visual_review import PROTOCOL as REVIEW_PROTOCOL
    folder = external_directory(folder)
    previous_workspace = __import__('lab').WORKSPACE
    from lab import configure_workspace
    output = inside(folder/('startup-probe-' + str(time.time_ns())))
    external_directory(output); output.mkdir(parents=True)
    try:
        configure_workspace(output)
        candidate = {'run':{'id':'renderer-startup-probe'}, 'exam':{'title':'Prueba observable del renderer'},
                     'questions':[], 'sources':[], 'assets':[]}
        write(output/'candidate.json', candidate)
        snapshot = output/'reviews/probe'; snapshot.mkdir(parents=True)
        for name in ('block-renderer.js', 'block-renderer.css'):
            shutil.copyfile(RUNTIME_ROOT/'viewer'/name, snapshot/name)
        shutil.copytree(RUNTIME_ROOT/'viewer/vendor/katex', snapshot/'vendor/katex')
        data = {'candidate':candidate, 'candidate_sha256':digest(output/'candidate.json'),
                'pages':[], 'question_pages':{}, 'requirements':{}}
        encoded = json.dumps(data, ensure_ascii=False).replace('<', r'\u003c').replace('&', r'\u0026')
        (snapshot/'index.html').write_text(HTML.replace('__DATA__', encoded), encoding='utf-8')
        record = {'protocol':REVIEW_PROTOCOL,'run_id':candidate['run']['id'],'questions':{},
            'files':[{'path':p.relative_to(output).as_posix(),'sha256':digest(p)}
                     for p in sorted(snapshot.rglob('*')) if p.is_file()]}
        path = snapshot/'render-review.json'; write(path, record)
        result = capture_review(output, {'path':path.relative_to(output).as_posix(),'sha256':digest(path)},
                                executable_path=executable_path, transport=transport)
        receipt = result['capture_receipt']
        return {'status':result['status'], 'renderer_probe':True, 'review_status':'pending',
            'certification':'not_performed',
            'capture_receipt':{'path':(output/receipt['path']).relative_to(folder).as_posix(),
                               'sha256':receipt['sha256']},
            **({'capability_probe':{**result['capability_probe'],
                'path':(output/result['capability_probe']['path']).relative_to(folder).as_posix()}}
               if result.get('capability_probe') else {}),
            **({'limitation':result['limitation']} if result.get('limitation') else {}),
            'next':'Inspect the observable probe image; rendering does not establish visual comprehension.'}
    finally:
        if previous_workspace is not None:
            configure_workspace(previous_workspace)
