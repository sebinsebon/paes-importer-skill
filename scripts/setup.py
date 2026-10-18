"""Install runtime requirements into an external environment; no browser downloads."""
import argparse
import os
import shutil
import subprocess
import sys
sys.dont_write_bytecode = True
import venv
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'shared/scripts'))
from runtime_environment import default_environment, environment_python, external_directory, process_environment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-dir', type=Path)
    parser.add_argument('--print-python', action='store_true', help='Print interpreter path without writing')
    parser.add_argument('--with-visual', action='store_true', help='Install optional capture Python dependencies; never browsers')
    args = parser.parse_args()
    if sys.version_info < (3, 12):
        raise SystemExit('Python 3.12+ required')
    if args.env_dir is not None and not args.env_dir.is_absolute():
        raise SystemExit('--env-dir must be absolute and outside the skill installation')
    environment = external_directory(args.env_dir) if args.env_dir else default_environment()
    python = environment_python(environment)
    if args.print_python:
        print(python)
        return
    node = shutil.which('node')
    if not node:
        raise SystemExit('Node.js 18+ required on PATH')
    version = subprocess.run([node, '--version'], capture_output=True, text=True, check=True).stdout.strip()
    if not version.startswith('v') or not version[1:].split('.')[0].isdigit() or int(version[1:].split('.')[0]) < 18:
        raise SystemExit('Node.js 18+ required; found ' + version)
    requirements = [ROOT/'requirements.txt']
    if args.with_visual:
        requirements.append(ROOT/'requirements-visual.txt')
    if any(not item.is_file() for item in requirements):
        raise SystemExit('Required dependency manifest missing')
    if environment.exists() and not ((environment/'pyvenv.cfg').is_file() and python.is_file()):
        raise SystemExit('Preserve existing directory; select a fresh path or existing virtual environment')
    env = process_environment(environment.parent, create=True)
    if not environment.exists():
        previous = dict(os.environ)
        try:
            os.environ.update(env)
            venv.EnvBuilder(with_pip=True).create(environment)
        finally:
            os.environ.clear()
            os.environ.update(previous)
    for manifest in requirements:
        subprocess.run([str(python), '-B', '-m', 'pip', 'install', '-r', str(manifest)], check=True, env=env)
    print('Ready: ' + str(python))
    if args.with_visual:
        print('Optional Python capture dependencies installed. No browser was downloaded.')
        print('Use an existing browser with --executable-path, or install a browser separately explicitly.')
        print('External browser cache: ' + env['PLAYWRIGHT_BROWSERS_PATH'])


if __name__ == '__main__':
    main()
