"""Exercise the distributed bundle without a checkout or a matching working directory."""
import json
import re
import os
import runpy
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class PortabilityTests(unittest.TestCase):
    def test_bundle_runs_from_unrelated_directory(self):
        (ROOT / 'tmp').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / 'tmp') as temporary:
            workspace = Path(temporary)
            caller = workspace / 'caller'
            caller.mkdir()
            environment = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONUTF8': '1',
                           'TEMP': str(workspace), 'TMP': str(workspace), 'TMPDIR': str(workspace)}
            environment.pop('PYTHONPATH', None)

            def run(*arguments):
                result = subprocess.run([sys.executable, '-B', *map(str, arguments)],
                                        cwd=caller, env=environment, capture_output=True,
                                        text=True, encoding='utf-8', timeout=180)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result

            bundle = workspace / 'skill.zip'
            run(ROOT / 'scripts/make_bundle.py', '--output', bundle)
            extracted = workspace / 'instalación con espacios'
            manifest = json.loads((ROOT / 'release.json').read_text(encoding='utf-8'))
            with zipfile.ZipFile(bundle) as archive:
                self.assertEqual(set(archive.namelist()),
                                 {'paes-importer/' + entry['path'] for entry in manifest['files']}
                                 | {'paes-importer/release.json'})
                archive.extractall(extracted)
            skill = extracted / 'paes-importer'
            self.assertFalse((skill / '.git').exists())
            self.assertFalse((skill / '.venv').exists())
            run(skill / 'scripts/release.py')
            run(skill / 'scripts/importer.py', '--help')
            # The distributed skill includes no development inputs.
            forbidden = {'tests', 'examples', 'docs', 'development', '.github',
                         'AGENTS.md', 'requirements-dev.txt', '.gitignore', '.gitattributes'}
            self.assertTrue(all(not (skill / name).exists() for name in forbidden))
            self.assertTrue((skill / 'references/hosts.md').is_file())
            # Agent-facing links must resolve inside the extracted bundle.
            for markdown in [skill / 'README.md', skill / 'SKILL.md',
                             *(skill / 'references').rglob('*.md'),
                             *(skill / 'shared/references').rglob('*.md')]:
                content = markdown.read_text(encoding='utf-8')
                for target in re.findall(r'\]\(([^)]+)\)', content):
                    if target.startswith(('http://', 'https://', '#', 'mailto:')):
                        continue
                    path = target.split('#', 1)[0]
                    if path:
                        self.assertTrue((markdown.parent / path).is_file(),
                                        f'Broken bundled link: {markdown}: {target}')
            run(skill / 'scripts/verify.py', '--help')
            # Smoke test: create a synthetic PDF outside the bundle and prepare it.
            sources = workspace / 'sources'
            run(ROOT / 'examples/synthetic.py', '--output', sources)
            capabilities = workspace / 'capabilities.json'
            capabilities.write_text(json.dumps({
                'pdf_visual': True, 'crop': True, 'execute': True,
                'zip': True, 'validate': True,
                'observation': 'Synthetic fixtures only, not an AI reading claim'
            }), encoding='utf-8')
            result = run(skill / 'scripts/importer.py', 'prepare',
                         '--exam', sources / 'synthetic-m1.pdf',
                         '--solution', sources / 'synthetic-key.pdf',
                         '--host', 'cli', '--client', 'bundle-smoke-test',
                         '--session-id', 'synthetic-smoke-test',
                         '--destination', 'custom', '--output-root', workspace / 'output',
                         '--capabilities', capabilities, '--run-id', 'bundle-smoke-test')
            self.assertTrue((Path(json.loads(result.stdout)['run']) / 'catalog.json').is_file())

    def test_setup_rejects_missing_node_before_creating_environment(self):
        with patch.object(sys, 'argv', ['setup.py']), patch('shutil.which', return_value=None):
            with self.assertRaisesRegex(SystemExit, 'Node.js 18'):
                runpy.run_path(str(ROOT / 'scripts/setup.py'), run_name='__main__')

    def test_setup_rejects_old_node_before_creating_environment(self):
        with patch.object(sys, 'argv', ['setup.py']), patch('shutil.which', return_value='node'), \
             patch('subprocess.run', return_value=subprocess.CompletedProcess(['node'], 0, 'v16.20.2\n')):
            with self.assertRaisesRegex(SystemExit, 'Node.js 18'):
                runpy.run_path(str(ROOT / 'scripts/setup.py'), run_name='__main__')


if __name__ == '__main__':
    unittest.main(verbosity=2)
