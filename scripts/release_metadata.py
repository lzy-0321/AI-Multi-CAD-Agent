"""Validate release identity and derive publication type from the package version."""
import argparse
import os
import re
import tomllib
from pathlib import Path


def metadata(version, tag):
    expected = 'v' + version
    if tag != expected:
        raise ValueError(f'Release tag {tag!r} does not match package version {version!r}; expected {expected!r}. '
                         'Update pyproject.toml before creating the tag. Re-running the old tag will not change its source.')
    match = re.fullmatch(r'\d+\.\d+\.\d+(?P<preview>(?:a|b|rc)\d+)?', version)
    if not match:
        raise ValueError(f'Unsupported release version: {version!r}; use X.Y.Z or X.Y.ZrcN')
    return {'version': version, 'tag': tag, 'prerelease': bool(match['preview']),
            'status': 'candidate' if match['preview'] else 'release'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--tag', required=True)
    args = parser.parse_args()
    version = tomllib.loads(Path('pyproject.toml').read_text(encoding='utf-8'))['project']['version']
    try:
        result = metadata(version, args.tag)
        if not Path(f'docs/releases/{args.tag}.md').is_file():
            raise ValueError(f'Missing release notes: docs/releases/{args.tag}.md')
    except ValueError as error:
        parser.exit(1, str(error) + '\n')
    print(f"Validated {result['tag']}: {result['status']}")
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as output:
            output.write(f"prerelease={str(result['prerelease']).lower()}\n")


if __name__ == '__main__':
    main()
