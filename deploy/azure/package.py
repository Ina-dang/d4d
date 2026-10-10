"""Build a source-only deployment archive; never include local keys, runs or .env."""

import hashlib
import json
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DESTINATION = ROOT / '.cache' / 'azure-deploy'


def main():
    DESTINATION.mkdir(parents=True, exist_ok=True)
    files = [ROOT / name for name in ('pyproject.toml', 'requirements.lock')]
    for directory in ('app', 'analysis', 'frame'):
        files.extend(p for p in (ROOT / directory).rglob('*') if p.is_file()
                     and '__pycache__' not in p.parts
                     and p.suffix not in {'.pyc', '.pyo'}
                     and not p.name.startswith(('.env', 'collected')))
    files.extend(p for p in (ROOT / 'docs').iterdir() if p.is_file()
                 and p.suffix in {'.html', '.css', '.js', '.png', '.svg'})
    files.extend(p for p in (ROOT / 'deploy' / 'azure').iterdir() if p.is_file()
                 and p.suffix in {'.sh', '.service'})
    manifest = {}
    archive = DESTINATION / 'gyeopnun-source.tar.gz'
    with tarfile.open(archive, 'w:gz') as output:
        for path in sorted(set(files)):
            if path.is_symlink() or not path.resolve().is_relative_to(ROOT):
                raise ValueError(f'Unexpected source path: {path}')
            name = path.relative_to(ROOT).as_posix()
            output.add(path, arcname=name, recursive=False)
            manifest[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    (DESTINATION / 'source-manifest.json').write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps({'archive': str(archive), 'files': len(manifest),
                      'bytes': archive.stat().st_size,
                      'sha256': hashlib.sha256(archive.read_bytes()).hexdigest()}))


if __name__ == '__main__':
    main()
