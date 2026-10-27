"""Audit the encoded delivery file; optional score comparison checks audio offset/drift."""
import argparse
import hashlib
import json
import math
import shutil
import subprocess
import sys
from fractions import Fraction
from pathlib import Path


def executable(value, name, sibling=None):
    found = value or shutil.which(name)
    if not found and sibling:
        candidate = Path(sibling).with_name(name + ('.exe' if Path(sibling).suffix.lower() == '.exe' else ''))
        found = candidate if candidate.is_file() else None
    if not found or not Path(found).is_file():
        raise ValueError(f'{name} not found; pass its executable path')
    return str(found)


def checked(args, timeout=180):
    result = subprocess.run(list(map(str, args)), capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(result.stderr[-1500:].decode('utf-8', 'replace'))
    return result.stdout


def compare_audio(ffmpeg, video, score, duration):
    import numpy as np
    rate = 8000
    window = min(3., duration / 3)
    positions = sorted(set(max(0., min(duration - window, (duration - window) * q)) for q in (.03, .33, .66, .92)))
    def pcm(file, start):
        raw = checked([ffmpeg, '-v', 'error', '-ss', start, '-i', file, '-t', window, '-ac', '1', '-ar', rate, '-f', 'f32le', '-'])
        values = np.frombuffer(raw, dtype='<f4').astype('float64')
        return values - values.mean() if len(values) else values
    results = []
    for start in positions:
        x, y = pcm(score, start), pcm(video, start)
        n = min(len(x), len(y))
        if n < 800:
            raise ValueError('Score/video audio too short for synchronization check')
        x, y = x[:n], y[:n]
        norm = math.sqrt(float(np.sum(x * x) * np.sum(y * y)))
        if norm < 1e-12:
            results.append({'time': start, 'measurable': False, 'reason': 'silent segment'})
            continue
        size = 1 << (2 * n - 1).bit_length()
        correlation = np.fft.irfft(np.fft.rfft(y, size) * np.conj(np.fft.rfft(x, size)), size)
        lags = np.arange(-1000, 1001)
        values = correlation[lags % size]
        peak = int(np.argmax(values))
        results.append({'time': start, 'measurable': True, 'delayMs': float(lags[peak]) * 1000 / rate, 'correlation': float(values[peak] / norm)})
    return results


def file_hash(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def audit(args):
    if not args.video.is_file():
        raise ValueError('Video does not exist')
    ffmpeg = executable(args.ffmpeg, 'ffmpeg')
    ffprobe = executable(args.ffprobe, 'ffprobe', ffmpeg)
    plan = json.loads(args.plan.read_text(encoding='utf-8-sig')) if args.plan else {}
    fps = Fraction(str(plan.get('fps', args.fps)))
    duration = plan.get('duration')
    if fps <= 0 or not all(v > 0 for v in (args.width, args.height, args.max_sync_ms)):
        raise ValueError('Video specifications and synchronization tolerance must be positive')
    info = json.loads(checked([ffprobe, '-v', 'error', '-count_frames', '-show_streams', '-show_format', '-of', 'json', args.video]))
    video = next((s for s in info.get('streams', []) if s.get('codec_type') == 'video'), None)
    audio = next((s for s in info.get('streams', []) if s.get('codec_type') == 'audio'), None)
    if not video:
        raise ValueError('No video stream')
    problems = []
    if (video['width'], video['height']) != (args.width, args.height):
        problems.append('Unexpected video dimensions')
    if Fraction(video['avg_frame_rate']) != fps:
        problems.append('Unexpected video frame rate')
    if video['codec_name'] != 'h264' or video.get('pix_fmt') != 'yuv420p':
        problems.append('Expected H.264/yuv420p delivery')
    if not audio and not args.allow_silent:
        problems.append('Expected an audio stream')
    actual_duration = float(video.get('duration', info['format']['duration']))
    actual_frames = int(video.get('nb_read_frames', video.get('nb_frames', 0)))
    if duration is not None:
        expected_frames = plan.get('totalFrames', round(float(duration) * float(fps)))
        if actual_frames != expected_frames:
            problems.append(f'Frame count differs: {actual_frames} vs {expected_frames}')
        if abs(actual_duration - duration) > 1 / float(fps) + .005:
            problems.append('Video duration differs from the cue plan')
        if abs(float(info['format']['duration']) - duration) > .1:
            problems.append('Container/audio tail differs from the cue plan')
    checked([ffmpeg, '-v', 'error', '-xerror', '-i', args.video, '-f', 'null', '-'], timeout=max(60, int(actual_duration * 4)))
    sync = []
    if args.score:
        if not args.score.is_file() or not audio:
            raise ValueError('--score requires an existing score and video audio stream')
        score_info = json.loads(checked([ffprobe, '-v', 'error', '-show_entries', 'format=duration', '-of', 'json', args.score]))
        if float(score_info['format']['duration']) < actual_duration - .05:
            problems.append('Score is shorter than the final video')
        sync = compare_audio(ffmpeg, args.video, args.score, actual_duration)
        measured = [s for s in sync if s['measurable']]
        if not measured:
            problems.append('No non-silent segments available to verify audio sync')
        elif any(abs(s['delayMs']) > args.max_sync_ms or s['correlation'] < .9 for s in measured):
            problems.append('Audio score comparison found delay, drift or content mismatch')
    report = {'video': str(args.video.resolve()), 'passed': not problems, 'issues': problems, 'bytes': args.video.stat().st_size, 'width': video['width'], 'height': video['height'], 'fps': video['avg_frame_rate'], 'duration': actual_duration, 'frames': actual_frames, 'videoCodec': video['codec_name'], 'audioCodec': audio['codec_name'] if audio else None, 'fullDecodePassed': True, 'audioSyncChecked': bool(args.score), 'audioSync': sync, 'visualCueFramesStillRequireReview': True}
    report.update(videoSha256=file_hash(args.video), planSha256=file_hash(args.plan) if args.plan else None, scoreSha256=file_hash(args.score) if args.score else None)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'report': str(args.out), 'passed': report['passed'], 'issues': problems, 'duration': actual_duration, 'frames': actual_frames, 'audioSyncChecked': report['audioSyncChecked']}, ensure_ascii=False))
    return not problems


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--video', type=Path, required=True)
    p.add_argument('--plan', type=Path)
    p.add_argument('--score', type=Path)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--width', type=int, default=1920)
    p.add_argument('--height', type=int, default=1080)
    p.add_argument('--fps', type=int, default=30)
    p.add_argument('--ffmpeg')
    p.add_argument('--ffprobe')
    p.add_argument('--max-sync-ms', type=float, default=10)
    p.add_argument('--allow-silent', action='store_true')
    args = p.parse_args()
    try:
        if not audit(args):
            p.exit(1)
    except (ValueError, OSError, RuntimeError, subprocess.TimeoutExpired, KeyError, ImportError) as error:
        p.exit(1, str(error)[:1500] + '\n')


if __name__ == '__main__':
    main()
