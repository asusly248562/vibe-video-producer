"""Record project artifacts and report missing, modified or unverified deliveries."""
import argparse
import hashlib
import json
import os
import struct
import sys
from pathlib import Path

KINDS = {'music-source', 'score', 'sources', 'storyboard', 'beat-map', 'preview', 'video', 'cover-4x3', 'cover-3x4', 'publish', 'render-audit', 'visual-review'}
SCOPES = {
    'full': ['sources', 'storyboard', 'beat-map', 'video', 'render-audit', 'visual-review', 'cover-4x3', 'cover-3x4', 'publish'],
    'video': ['sources', 'storyboard', 'beat-map', 'video', 'render-audit', 'visual-review'],
    'covers': ['cover-4x3', 'cover-3x4'],
    'cover-4x3': ['cover-4x3'],
    'cover-3x4': ['cover-3x4'],
    'copy': ['publish'],
}


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def inside(root, value):
    path = (root / value).resolve()
    if not path.is_relative_to(root):
        raise ValueError('Artifact must remain inside the project directory')
    if not path.is_file():
        raise ValueError('Artifact file does not exist')
    return path


def load(path):
    value = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(value, dict):
        raise ValueError('Expected a JSON object: ' + path.name)
    return value


def image_size(path):
    """Read PNG/JPEG dimensions without importing an image renderer."""
    with path.open('rb') as stream:
        header = stream.read(24)
        if header[:8] == b'\x89PNG\r\n\x1a\n' and header[12:16] == b'IHDR' and len(header) == 24:
            return struct.unpack('>II', header[16:24])
        stream.seek(0)
        if stream.read(2) != b'\xff\xd8':
            raise ValueError('Cover must be a PNG or JPEG image')
        sof = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
        while stream.tell() < 1024 * 1024:
            if stream.read(1) != b'\xff':
                raise ValueError('Malformed JPEG header')
            marker = stream.read(1)
            while marker == b'\xff':
                marker = stream.read(1)
            if not marker or marker[0] in (0xD9, 0xDA):
                break
            if marker[0] in (0x01, *range(0xD0, 0xD9)):
                continue
            raw = stream.read(2)
            if len(raw) != 2:
                break
            size = int.from_bytes(raw, 'big')
            if size < 2:
                break
            if marker[0] in sof:
                values = stream.read(5)
                if len(values) == 5:
                    height, width = struct.unpack('>HH', values[1:])
                    return width, height
                break
            stream.seek(size - 2, 1)
    raise ValueError('Could not read valid cover dimensions')


def validate_artifact(kind, path):
    if path.stat().st_size == 0:
        raise ValueError('Artifact is empty')
    metadata = {}
    if kind.startswith('cover-'):
        width, height = image_size(path)
        a, b = (4, 3) if kind == 'cover-4x3' else (3, 4)
        if min(width, height) <= 0 or width * b != height * a:
            raise ValueError(f'Expected cover ratio {a}:{b}, got {width}x{height}')
        metadata.update(width=width, height=height)
    if kind in {'storyboard', 'beat-map', 'render-audit', 'visual-review'}:
        load(path)
    if kind == 'video' and path.suffix.lower() != '.mp4':
        raise ValueError('Delivery video must be MP4')
    return metadata


def record(root, spec, kind, value):
    path = inside(root, value)
    extra = validate_artifact(kind, path)
    spec.setdefault('artifacts', {})[kind] = {'path': path.relative_to(root).as_posix(), 'sha256': digest(path), 'bytes': path.stat().st_size, **extra}
    spec['schemaVersion'] = 2
    destination = root / 'project.json'
    backup = root / 'project.previous.json'
    if not destination.resolve().is_relative_to(root) or not backup.resolve().is_relative_to(root):
        raise ValueError('Project metadata must remain inside the project')
    serialized = json.dumps(spec, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    # In-place writes work in Windows sandboxes that grant write but not rename.
    # Keep the last valid document so interrupted writes can be recovered.
    backup.write_text(destination.read_text(encoding='utf-8-sig'), encoding='utf-8')
    with destination.open('w', encoding='utf-8', newline='\n') as stream:
        stream.write(serialized)
        stream.flush()
        os.fsync(stream.fileno())
    return {'recorded': kind, 'path': str(path)}


def status(root, spec, scope):
    required = list(SCOPES[scope])
    if scope in {'full', 'video'} and spec.get('music'):
        required.extend(['music-source', 'score'])
    artifacts = spec.get('artifacts', {})
    if not isinstance(artifacts, dict):
        raise ValueError('project.json artifacts must be an object')
    missing, invalid, paths, entries = [], [], {}, {}
    def problem(kind, reason):
        invalid.append({'kind': kind, 'reason': reason})
    for kind in required:
        entry = artifacts.get(kind)
        if entry is None:
            missing.append(kind)
            continue
        try:
            if not isinstance(entry, dict) or not isinstance(entry.get('path'), str):
                raise ValueError('Malformed artifact record')
            path = inside(root, entry['path'])
            if digest(path) != entry.get('sha256'):
                raise ValueError('File changed since it was recorded; revalidate before recording again')
            validate_artifact(kind, path)
            paths[kind], entries[kind] = path, entry
        except (ValueError, OSError) as error:
            problem(kind, str(error))
    def binding(report, field, kind):
        return kind in entries and report.get(field) == entries[kind]['sha256']
    if 'render-audit' in paths:
        report = load(paths['render-audit'])
        if report.get('passed') is not True or report.get('fullDecodePassed') is not True:
            problem('render-audit', 'Actual delivery did not pass full render audit')
        for field, kind in [('videoSha256', 'video'), ('planSha256', 'beat-map')]:
            if not binding(report, field, kind):
                problem('render-audit', 'Audit is not bound to current ' + kind)
        if spec.get('music') and (report.get('audioSyncChecked') is not True or not binding(report, 'scoreSha256', 'score')):
            problem('render-audit', 'Current final score requires an audio synchronization audit')
    if 'visual-review' in paths:
        report = load(paths['visual-review'])
        if any(report.get(key) is not True for key in ['passed', 'fontsChecked', 'knowledgeChecked']):
            problem('visual-review', 'Picture, phone typography and knowledge review must be recorded')
        for field, kind in [('videoSha256', 'video'), ('planSha256', 'beat-map'), ('sourcesSha256', 'sources'), ('storyboardSha256', 'storyboard')]:
            if not binding(report, field, kind):
                problem('visual-review', 'Review is not bound to current ' + kind)
        if 'beat-map' in paths:
            cues = load(paths['beat-map']).get('cues', [])
            checked = report.get('checkedFrames', [])
            if not isinstance(cues, list) or not cues or any(not isinstance(c, dict) or not isinstance(c.get('frame'), int) for c in cues):
                problem('visual-review', 'Cue plan is missing valid frame events')
            elif not isinstance(checked, list) or any(not isinstance(f, int) or isinstance(f, bool) for f in checked) or not {c['frame'] for c in cues}.issubset(set(checked)):
                problem('visual-review', 'Not all cut/keyword/formula cue frames were reviewed')
    ready = not missing and not invalid
    stage = 'ready-to-deliver' if ready else ('render-needs-review' if 'video' in paths else 'in-progress')
    return {'project': str(root), 'scope': scope, 'stage': stage, 'readyToDeliver': ready, 'missing': missing, 'invalid': invalid, 'registeredArtifacts': len(artifacts), 'note': 'This checks recorded files and review evidence, not artistic quality or user authorization.'}


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    a = sub.add_parser('record')
    a.add_argument('--project', type=Path, required=True)
    a.add_argument('--kind', choices=sorted(KINDS), required=True)
    a.add_argument('--path', type=Path, required=True)
    b = sub.add_parser('status')
    b.add_argument('--project', type=Path, required=True)
    b.add_argument('--scope', choices=SCOPES, default='full')
    b.add_argument('--out', type=Path)
    b.add_argument('--require-ready', action='store_true')
    args = parser.parse_args()
    try:
        root = args.project.resolve()
        if not (root / 'project.json').resolve().is_relative_to(root):
            raise ValueError('Project metadata must remain inside the project')
        spec = load(root / 'project.json')
        result = record(root, spec, args.kind, args.path) if args.command == 'record' else status(root, spec, args.scope)
        if args.command == 'status' and args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False))
        if args.command == 'status' and args.require_ready and not result['readyToDeliver']:
            parser.exit(1)
    except (ValueError, OSError, KeyError) as error:
        parser.exit(1, str(error)[:1500] + '\n')


if __name__ == '__main__':
    main()
