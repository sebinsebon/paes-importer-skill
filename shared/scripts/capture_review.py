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
    header = Path(path).read_bytes()[:24]
    if len(header) != 24 or header[:8] != b'\x89PNG\r\n\x1a\n' or header[12:16] != b'IHDR':
        raise ValueError('Capture is not a PNG image')
    size = struct.unpack('>II', header[16:24])
    if min(size) < 1:
        raise ValueError('Capture has empty dimensions')
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


def capture_review(folder, reference, *, executable_path=None, transport='auto'):
    """Capture a current snapshot into a fresh run directory; preserve failures."""
    from visual_review import validate_review
    if transport not in ('auto', 'file', 'memory'):
        raise ValueError('Capture transport must be auto, file or memory')
    folder = external_directory(folder)
    candidate = read(folder/'candidate.json')
    for question in candidate['questions']:
        validate_review(folder, reference, question, candidate)
    snapshot = artifact_path(folder, reference['path'], 'reviews').parent
    if executable_path is not None:
        # Reading an existing system browser may legitimately follow /usr/bin links.
        # Browser profiles and generated files still use validated external paths.
        executable_path = Path(executable_path).expanduser().resolve(strict=True)
        if not executable_path.is_file() or executable_path.is_relative_to(RUNTIME_ROOT):
            raise ValueError('Explicit browser executable does not exist')
    output = inside(folder/'reviews'/('capture-' + str(time.time_ns())))
    external_directory(output)
    if output.exists():
        raise ValueError('Select a fresh capture directory')
    output.mkdir(parents=True)
    manifest = {'protocol': PROTOCOL, 'status': 'running', 'render_review': reference,
                'run_id': candidate['run']['id'], 'screenshots': [],
                'review_status': 'pending', 'certification': 'not_performed'}
    manifest_path = output/'capture-manifest.json'
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
                def load_memory():
                    context.unroute('**/*')
                    context.route('**/*', lambda route: memory_request(route, snapshot))
                    html = (snapshot/'index.html').read_text(encoding='utf-8')
                    html = html.replace('<head>', '<head><base href="https://paes-review.invalid/">', 1)
                    page.set_content(html, wait_until='load', timeout=30000)
                    manifest['transport'] = 'memory'
                if transport == 'memory':
                    load_memory()
                else:
                    try:
                        page.goto((snapshot/'index.html').as_uri(), wait_until='load', timeout=30000)
                        manifest['transport'] = 'file'
                    except Exception as error:
                        if transport != 'auto' or not any(code in str(error) for code in (
                                'ERR_BLOCKED_BY_ADMINISTRATOR', 'ERR_ACCESS_DENIED', 'Not allowed to load local resource')):
                            raise
                        manifest['file_limitation'] = str(error)
                        load_memory()
                page.wait_for_function('window.__PAES_REVIEW_READY__ === true', timeout=30000)
                page.evaluate('''async () => {
                    await document.fonts.ready;
                    await Promise.all(Array.from(document.images, img => img.complete ? Promise.resolve() :
                        new Promise((resolve,reject) => {img.onload=resolve;img.onerror=()=>reject(new Error('Image load failed'));})));
                    if (Array.from(document.images).some(img => !img.naturalWidth)) throw new Error('Image not rendered');
                }''')
                if page.locator('#errors').inner_text().strip():
                    raise ValueError('Rendered review reports mathematical or content errors')
                sections = page.locator('section.question')
                ids = sections.evaluate_all('(nodes) => nodes.map(node => node.dataset.questionId)')
                if ids != [q['id'] for q in candidate['questions']]:
                    raise ValueError('Rendered question inventory differs from snapshot')
                for index, question in enumerate(candidate['questions']):
                    image = output/('question-' + str(index+1).zfill(5) + '.png')
                    sections.nth(index).screenshot(path=str(image), animations='disabled', caret='hide', timeout=30000)
                    manifest['screenshots'].append({'question_id': question['id'],
                        'path': image.relative_to(folder).as_posix(), 'sha256': digest(image),
                        'size': _png_size(image)})
                manifest['browser'] = {'engine': 'chromium', 'version': browser.version,
                                       'source': 'explicit-executable' if executable_path else 'external-managed-cache'}
                manifest['status'] = 'captured'
            finally:
                browser.close()
    except Exception as error:
        # No install/download attempt is made. Keep any images already produced for diagnosis.
        manifest.update(status='unavailable', limitation=type(error).__name__ + ': ' + str(error))
    finally:
        os.environ.clear()
        os.environ.update(previous_environment)
        write(manifest_path, manifest)
    return {**manifest, 'capture_receipt': {'path': manifest_path.relative_to(folder).as_posix(),
                                           'sha256': digest(manifest_path)},
            'next': 'Inspect the screenshots and record the observation; capture generation does not perform visual review.'
                    if manifest['status'] == 'captured' else
                    'Use native HTML inspection or an explicitly installed optional capture tool. Visual review remains pending.'}


def validate_capture(folder, receipt, reference, question_id):
    if not isinstance(receipt, dict) or set(receipt) != {'path', 'sha256'}:
        raise ValueError('Image observation needs its capture_receipt')
    path = artifact_path(folder, receipt['path'], 'reviews')
    if not path.is_file() or digest(path) != receipt['sha256']:
        raise ValueError('Altered capture receipt')
    record = read(path)
    if record.get('protocol') != PROTOCOL or record.get('status') != 'captured' or record.get('render_review') != reference:
        raise ValueError('Capture receipt is incomplete or belongs to another render review')
    screenshots = record.get('screenshots')
    if not isinstance(screenshots, list) or not screenshots:
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
    if question_id not in seen:
        raise ValueError('Capture does not include this question')
    return record
