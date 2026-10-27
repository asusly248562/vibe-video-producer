"""Create an isolated Vibe project and record user inputs; no rendering side effects."""
import argparse
import hashlib
import json
import re
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workspace', type=Path, required=True)
    p.add_argument('--slug', required=True)
    p.add_argument('--topic', required=True)
    p.add_argument('--music', type=Path)
    p.add_argument('--width', type=int, default=1920)
    p.add_argument('--height', type=int, default=1080)
    p.add_argument('--fps', type=int, default=30)
    args = p.parse_args()
    slug = re.sub(r'[^\w\-]+', '-', args.slug, flags=re.UNICODE).strip('-_')[:60]
    if not slug or not args.topic.strip() or min(args.width, args.height, args.fps) <= 0:
        p.error('Use a nonempty topic/slug and positive video dimensions/fps')
    if args.music and (not args.music.is_file() or args.music.suffix.lower() not in {'.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg'}):
        p.error('--music must be an existing audio file')
    workspace = args.workspace.resolve()
    if not workspace.is_dir():
        p.error('--workspace must be an existing directory')
    now = datetime.now(timezone(timedelta(hours=8)))
    base = workspace / f'vibe_{slug}_{now:%Y%m%d}'
    root = base
    suffix = 2
    while root.exists():
        root = base.with_name(base.name + f'_{suffix}')
        suffix += 1
    root.mkdir()
    for folder in ('assets', 'src', 'compositions', 'covers', 'verification', 'final'):
        (root / folder).mkdir()
    defaults = json.loads((Path(__file__).resolve().parents[1] / 'assets' / 'defaults.json').read_text(encoding='utf-8'))
    defaults['video'].update(width=args.width, height=args.height, fps=args.fps)
    music = None
    artifacts = {}
    if args.music:
        target = root / 'assets' / ('music-source' + args.music.suffix.lower())
        shutil.copyfile(args.music, target)
        music = {'original': str(args.music.resolve()), 'local': target.relative_to(root).as_posix(), 'sourceOffset': None, 'speed': 1}
        digest = hashlib.sha256()
        with target.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
        artifacts['music-source'] = {'path': music['local'], 'sha256': digest.hexdigest(), 'bytes': target.stat().st_size}
    spec = {'schemaVersion': 2, 'skillVersion': '0.2.0', 'topic': args.topic.strip(), 'createdAt': now.isoformat(), 'preferences': defaults, 'music': music, 'stage': 'inputs-recorded', 'artifacts': artifacts}
    (root / 'project.json').write_text(json.dumps(spec, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'project': str(root), 'musicCopied': music is not None, 'stage': spec['stage']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
