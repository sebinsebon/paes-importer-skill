"""Check bundled file hashes without writing into the installation."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def verify():
    manifest = json.loads((ROOT/'release.json').read_text(encoding='utf-8'))
    for record in manifest['files']:
        path = ROOT/record['path']
        if not path.resolve().is_relative_to(ROOT) or not path.is_file():
            raise ValueError('Missing/unsafe release file: '+record['path'])
        if hashlib.sha256(path.read_bytes()).hexdigest() != record['sha256']:
            raise ValueError('Release file changed: '+record['path'])
    return len(manifest['files'])

if __name__ == '__main__': print(str(verify())+' release files verified')
