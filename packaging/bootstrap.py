"""Bootstrap directly from the supplied pure-Python wheel; no source checkout needed."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

bundle = Path(__file__).resolve().parent
manifest = json.loads((bundle / 'release.json').read_text(encoding='utf-8'))
wheel = bundle / manifest['wheel']
if hashlib.sha256(wheel.read_bytes()).hexdigest() != manifest['sha256']:
    raise SystemExit('Release wheel checksum mismatch; obtain an intact release bundle')
sys.path.insert(0, str(wheel))
from multi_cad.release import install

parser = argparse.ArgumentParser()
parser.add_argument('--root', required=True)
args = parser.parse_args()
print(json.dumps(install(wheel, args.root, bundle / 'launch.ps1'), ensure_ascii=False, indent=2))
