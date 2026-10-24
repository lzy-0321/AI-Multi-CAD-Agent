"""Build a version-consistent Windows ZIP and external SHA-256 checksum."""
import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
import tomllib
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from multi_cad.install import SOURCES
from release_metadata import metadata

version = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))['project']['version']
release = metadata(version, 'v' + version)
dist = root / 'dist'
dist.mkdir(exist_ok=True)
subprocess.run([sys.executable, '-m', 'pip', 'wheel', '--no-deps',
                '--wheel-dir', str(dist), str(root)], check=True)
wheel = next(dist.glob(f'ai_multi_cad_agent-{version}-*.whl'))
bundle = dist / f'MultiCAD-{version}-windows'
bundle.mkdir(exist_ok=True)
for name in ('install.ps1', 'launch.ps1', 'bootstrap.py'):
    shutil.copy2(root / 'packaging' / name, bundle / name)
quick_en = (root / 'docs' / 'installation-quickstart.md').read_text(encoding='utf-8')
(bundle / 'QUICKSTART.md').write_text(
    quick_en.replace('](zh/installation-quickstart.md)', '](QUICKSTART.zh-CN.md)'), encoding='utf-8')
quick_zh = (root / 'docs' / 'zh' / 'installation-quickstart.md').read_text(encoding='utf-8')
(bundle / 'QUICKSTART.zh-CN.md').write_text(
    quick_zh.replace('](../installation-quickstart.md)', '](QUICKSTART.md)'), encoding='utf-8')
shutil.copy2(wheel, bundle / wheel.name)
manifest = {'version': version, 'status': release['status'], 'platform': 'windows',
            'cross_machine_verified': False, 'wheel': wheel.name,
            'sha256': hashlib.sha256(wheel.read_bytes()).hexdigest(), 'upstreams': SOURCES}
(bundle / 'release.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
archive = dist / (bundle.name + '.zip')
with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as output:
    # Publish only named build outputs, never leftover local files in the staging directory.
    for name in ('install.ps1', 'launch.ps1', 'bootstrap.py', 'QUICKSTART.md', 'QUICKSTART.zh-CN.md', 'release.json', wheel.name):
        output.write(bundle / name, bundle.name + '/' + name)
checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
archive.with_suffix('.zip.sha256').write_text(f'{checksum}  {archive.name}\n', encoding='ascii')
print(json.dumps({'zip': str(archive), 'sha256': checksum}, indent=2))
