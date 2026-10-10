"""Create or check the public bundle manifest; excludes private/generated artifacts."""
import argparse
import hashlib
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {'.git', '.venv', 'tmp', '__pycache__', 'EnsayosPaessedOutput', '.pytest_cache', 'Output', '.work'}
DIRECTORIES = {'scripts', 'shared', 'viewer', 'references'}
ROOT_FILES = {'SKILL.md', 'README.md', 'LICENSE', 'NOTICE.md', 'requirements.txt', 'run.ps1'}

def records():
    paths = sorted(ROOT.rglob('*'), key=lambda p: p.relative_to(ROOT).as_posix())
    return [{'path': p.relative_to(ROOT).as_posix(), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
            for p in paths if p.is_file()
            and not any(part in EXCLUDED for part in p.relative_to(ROOT).parts)
            and p.name != 'release.json' and p.suffix.lower() not in ('.pdf', '.zip', '.paessed', '.png')
            and (p.relative_to(ROOT).parts[0] in DIRECTORIES or p.relative_to(ROOT).as_posix() in ROOT_FILES)]

if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    manifest = {'version': '1.0.0-portable', 'protocol_version': '0.3.0', 'files': records()}
    if args.write:
        (ROOT / 'release.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8', newline='\n')
    else:
        recorded = json.loads((ROOT / 'release.json').read_text(encoding='utf-8'))
        if recorded != manifest:
            recorded_files = {item['path']: item['sha256'] for item in recorded.get('files', [])}
            current_files = {item['path']: item['sha256'] for item in manifest['files']}
            missing = sorted(set(recorded_files) - set(current_files))
            added = sorted(set(current_files) - set(recorded_files))
            changed = sorted(path for path in set(recorded_files) & set(current_files)
                             if recorded_files[path] != current_files[path])
            print('Release manifest mismatch:')
            for path in missing:
                print('  missing:', path)
            for path in added:
                print('  added:', path)
            for path in changed:
                print('  changed:', path)
            if recorded.get('version') != manifest.get('version'):
                print('  version:', recorded.get('version'), '!=', manifest.get('version'))
            if recorded.get('protocol_version') != manifest.get('protocol_version'):
                print('  protocol_version:', recorded.get('protocol_version'), '!=', manifest.get('protocol_version'))
            raise SystemExit(1)
        print(str(len(manifest['files'])) + ' release files verified')
