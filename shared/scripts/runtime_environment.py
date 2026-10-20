"""External environments and caches. This module has no third-party imports."""
import hashlib
import os
import platform
import sys
from pathlib import Path

RUNTIME_ROOT = Path(__file__).resolve().parents[2]


def external_path(path, *, runtime_root=RUNTIME_ROOT):
    """Validate before creating anything; reject linked and installation paths."""
    path = Path(path).expanduser().absolute()
    for item in (path, *path.parents):
        if item.is_symlink() or (hasattr(item, 'is_junction') and item.is_junction()):
            raise ValueError('Linked output path is forbidden: ' + str(item))
    path = path.resolve()
    root = Path(runtime_root).resolve()
    if path == Path(path.anchor):
        raise ValueError('A filesystem root cannot be an output directory')
    if path == root or path.is_relative_to(root):
        raise ValueError('Outputs, environments and caches must be outside the skill installation')
    return path


def external_directory(path, *, create=False, runtime_root=RUNTIME_ROOT):
    path = external_path(path, runtime_root=runtime_root)
    if path.exists() and not path.is_dir():
        raise ValueError('Expected an external directory: ' + str(path))
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def data_directory(*, environ=None, runtime_root=RUNTIME_ROOT):
    env = os.environ if environ is None else environ
    if env.get('PAES_IMPORTER_DATA_DIR'):
        path = Path(env['PAES_IMPORTER_DATA_DIR'])
        if not path.is_absolute():
            raise ValueError('PAES_IMPORTER_DATA_DIR must be absolute')
    elif sys.platform == 'win32':
        path = Path(env.get('LOCALAPPDATA', Path.home()/'AppData/Local'))/'PAESImporter'
    elif sys.platform == 'darwin':
        path = Path.home()/'Library/Application Support/PAESImporter'
    else:
        path = Path(env.get('XDG_DATA_HOME', Path.home()/'.local/share'))/'paes-importer'
    return external_directory(path, runtime_root=runtime_root)


def default_environment(*, environ=None, runtime_root=RUNTIME_ROOT):
    root = Path(runtime_root)
    identity = (root/'requirements.txt').read_bytes() + ('\n' + sys.implementation.cache_tag +
                '\n' + sys.platform + '\n' + platform.machine()).encode('utf-8')
    key = hashlib.sha256(identity).hexdigest()[:20]
    return external_directory(data_directory(environ=environ, runtime_root=root)/'environments'/key,
                              runtime_root=root)


def environment_python(environment):
    return Path(environment)/('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')


def process_environment(workspace, *, create=False, environ=None, runtime_root=RUNTIME_ROOT):
    """Return child-process settings without changing global state or installing tools."""
    workspace = external_directory(workspace, runtime_root=runtime_root)
    env = dict(os.environ if environ is None else environ)
    base = workspace/'.runtime'
    directories = {'TEMP': base/'tmp', 'TMP': base/'tmp', 'TMPDIR': base/'tmp',
                   'PIP_CACHE_DIR': base/'caches/pip', 'UV_CACHE_DIR': base/'caches/uv',
                   'PYTHONPYCACHEPREFIX': base/'caches/python',
                   'XDG_CACHE_HOME': base/'caches/xdg',
                   'PLAYWRIGHT_BROWSERS_PATH': Path(env['PLAYWRIGHT_BROWSERS_PATH'])
                       if env.get('PLAYWRIGHT_BROWSERS_PATH') else
                       data_directory(environ=env, runtime_root=runtime_root)/'caches/browsers'}
    validated = {key: external_directory(path, runtime_root=runtime_root)
                 for key, path in directories.items()}
    if create:
        for directory in set(validated.values()):
            directory.mkdir(parents=True, exist_ok=True)
    env.update({key: str(path) for key, path in validated.items()})
    env.update(PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1')
    return env
