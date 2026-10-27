"""Measure a candidate beat grid, then turn a beat-based storyboard into frame cues."""
import argparse
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path


def binary(value, name):
    found = value or shutil.which(name)
    if not found or not Path(found).is_file():
        raise ValueError(f'{name} not found; pass --{name} with the executable path')
    return str(found)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def analyze(args):
    import numpy as np
    if not args.music.is_file() or not finite_number(args.seconds) or not 4 <= args.seconds <= 180 or not finite_number(args.offset) or args.offset < 0:
        raise ValueError('Provide existing music, nonnegative offset and 4–180 analysis seconds')
    if args.bpm is not None and not 30 <= args.bpm <= 300:
        raise ValueError('--bpm must be within 30–300')
    sr, hop, win = 22050, 128, 2048
    result = subprocess.run([binary(args.ffmpeg, 'ffmpeg'), '-v', 'error', '-ss', str(args.offset), '-i', str(args.music), '-t', str(args.seconds), '-ac', '1', '-ar', str(sr), '-f', 'f32le', '-'], capture_output=True, timeout=90)
    if result.returncode:
        raise RuntimeError(result.stderr[-1500:].decode('utf-8', 'replace'))
    pcm = np.frombuffer(result.stdout, dtype='<f4')
    if len(pcm) < 4 * sr or not np.isfinite(pcm).all() or np.max(np.abs(pcm)) < 1e-6:
        raise ValueError('Audio is too short, invalid, or silent')
    windows = np.lib.stride_tricks.sliding_window_view(pcm, win)[::hop]
    hann = np.hanning(win)
    envelope = []
    previous = None
    for start in range(0, len(windows), 512):
        spectrum = np.log1p(np.abs(np.fft.rfft(windows[start:start + 512] * hann, axis=1)))
        if previous is not None:
            spectrum = np.vstack([previous, spectrum])
        delta = np.maximum(np.diff(spectrum, axis=0), 0)
        envelope.extend(delta.sum(axis=1).tolist())
        previous = spectrum[-1:]
    flux = np.asarray(envelope)
    flux = np.maximum(flux - np.convolve(flux, np.ones(64) / 64, mode='same'), 0)
    if flux.max() <= 0:
        raise ValueError('No usable onsets detected; supply another music section')
    times = (np.arange(len(flux)) + 1) * hop / sr + win / (2 * sr)
    sample_rate = sr / hop
    size = 1 << (2 * len(flux) - 1).bit_length()
    correlation = np.fft.irfft(np.abs(np.fft.rfft(flux, size)) ** 2, size)[:len(flux)]
    correlation /= np.arange(len(flux), 0, -1)
    first_lag = max(2, int(sample_rate * 60 / 170))
    last_lag = min(len(correlation) - 2, int(sample_rate * 60 / 70))
    lag = first_lag + int(np.argmax(correlation[first_lag:last_lag + 1]))
    left, centre, right = correlation[lag - 1:lag + 2]
    denominator = left - 2 * centre + right
    refined = lag + (float(np.clip(.5 * (left - right) / denominator, -.5, .5)) if denominator else 0)
    estimated_bpm = 60 * sample_rate / refined
    bpm = args.bpm or estimated_bpm
    period = 60 / bpm
    candidates = np.arange(0, period, .005)
    scores = [np.mean(np.interp(np.arange(phase, times[-1], period), times, flux, left=0, right=0)) for phase in candidates]
    phase = float(candidates[int(np.argmax(scores))])
    if args.first_beat is not None:
        if not 0 <= args.first_beat < len(pcm) / sr - period:
            raise ValueError('--first-beat must leave at least one beat in the analyzed section')
        phase = args.first_beat
    else:
        selection = np.flatnonzero((times >= phase - .04) & (times <= phase + .04))
        if len(selection):
            phase = float(times[selection[int(np.argmax(flux[selection]))]])
    raw_beats = np.arange(phase, len(pcm) / sr - win / (2 * sr), period)
    beat_times = [round(float(t - phase), 9) for t in raw_beats]
    onset_times, strengths = [], []
    threshold = float(np.quantile(flux, .6))
    for predicted in raw_beats:
        selected = np.flatnonzero((times >= predicted - .045) & (times <= predicted + .045))
        if len(selected):
            j = selected[int(np.argmax(flux[selected]))]
            strength = float(flux[j])
            onset = float(times[j]) if strength > threshold else float(predicted)
        else:
            strength, onset = 0., float(predicted)
        onset_times.append(round(onset - phase, 9))
        strengths.append(strength)
    if len(beat_times) < 2:
        raise ValueError('Insufficient beats in the chosen section')
    onset_times[0] = 0.
    report = {'schemaVersion': 1, 'source': str(args.music.resolve()), 'analysisOffset': args.offset, 'analysisDuration': len(pcm) / sr, 'sourceOffset': args.offset + phase, 'estimatedBpm': estimated_bpm, 'bpm': bpm, 'beatPeriod': period, 'beatTimes': beat_times, 'onsetTimes': onset_times, 'onsetStrength': strengths, 'tempoIsEstimate': args.bpm is None, 'needsListeningReview': True, 'note': 'Tempo/phase are candidates. Check half/double time, downbeat and weak onsets; frame-rounding error does not measure beat-detection accuracy.'}
    write_json(args.out, report)
    return {'file': str(args.out), 'bpm': round(bpm, 3), 'sourceOffset': report['sourceOffset'], 'beats': len(beat_times), 'needsListeningReview': True}


def plan(args):
    grid = json.loads(args.grid.read_text(encoding='utf-8-sig'))
    story = json.loads(args.story.read_text(encoding='utf-8-sig'))
    if not isinstance(grid, dict) or not isinstance(story, dict):
        raise ValueError('Grid and storyboard must be JSON objects')
    if not finite_number(grid.get('sourceOffset')) or grid['sourceOffset'] < 0 or not finite_number(grid.get('bpm')) or grid['bpm'] <= 0:
        raise ValueError('Grid requires finite nonnegative sourceOffset and positive bpm')
    fps = story.get('fps', 30)
    if not isinstance(fps, int) or isinstance(fps, bool) or not 1 <= fps <= 240:
        raise ValueError('fps must be an integer within 1–240')
    beats = grid['onsetTimes' if args.snap_onsets else 'beatTimes']
    if not isinstance(beats, list) or len(beats) < 2 or not all(finite_number(t) for t in beats) or abs(beats[0]) > 1e-8 or any(b <= a for a, b in zip(beats, beats[1:])):
        raise ValueError('Beat times must start at zero and strictly increase')
    scenes = story.get('scenes', [])
    if not isinstance(scenes, list) or not scenes or any(not isinstance(s, dict) for s in scenes):
        raise ValueError('Storyboard has no scenes')
    used = set()
    total = 0
    for s in scenes:
        if not isinstance(s.get('beats'), int) or isinstance(s['beats'], bool) or s['beats'] <= 0:
            raise ValueError('Scene beats must be positive integers')
        sid = s.get('id')
        if not isinstance(sid, str) or not sid or sid in used:
            raise ValueError('Each scene requires a unique nonempty id')
        used.add(sid)
        total += s['beats']
    if total >= len(beats):
        raise ValueError(f'Need {total + 1} beat boundaries, only {len(beats)} available; analyze a longer section')
    def target(beat):
        i = int(math.floor(beat))
        f = beat - i
        return beats[i] if f == 0 else beats[i] + f * (beats[i + 1] - beats[i])
    def cue(kind, sid, beat):
        seconds = target(beat)
        frame = int(math.floor(seconds * fps + .5))
        return {'type': kind, 'sceneId': sid, 'beat': beat, 'target': seconds, 'frame': frame, 't': frame / fps, 'roundingErrorMs': (frame / fps - seconds) * 1000}
    shots, cues, index = [], [], 0
    for s in scenes:
        start = cue('cut', s['id'], index)
        end = cue('end', s['id'], index + s['beats'])
        if end['frame'] <= start['frame']:
            raise ValueError('Scene duration is shorter than a frame')
        shots.append({**s, 'startBeat': index, 'startFrame': start['frame'], 'endFrame': end['frame'], 'start': start['t'], 'duration': (end['frame'] - start['frame']) / fps})
        cues.append(start)
        event_ids = set()
        events = s.get('events', [])
        if not isinstance(events, list) or any(not isinstance(e, dict) for e in events):
            raise ValueError('Scene events must be a list of objects')
        for event in events:
            b = event.get('beat')
            eid = event.get('id')
            if not isinstance(b, (int, float)) or isinstance(b, bool) or not math.isfinite(b) or not 0 <= b < s['beats'] or not isinstance(eid, str) or not eid or eid in event_ids:
                raise ValueError('Event needs a unique id and finite in-scene beat offset')
            event_ids.add(eid)
            cues.append(cue(eid, s['id'], index + b))
        index += s['beats']
    cues.sort(key=lambda c: c['frame'])
    report = {'schemaVersion': 1, 'fps': fps, 'sourceOffset': grid['sourceOffset'], 'bpm': grid['bpm'], 'snapOnsets': args.snap_onsets, 'duration': shots[-1]['endFrame'] / fps, 'totalFrames': shots[-1]['endFrame'], 'beatTimes': beats[:index + 1], 'shots': shots, 'cues': cues, 'cueMaxRoundingErrorMs': max(abs(c['roundingErrorMs']) for c in cues), 'beatDetectionNeedsReview': grid.get('needsListeningReview', True)}
    write_json(args.out, report)
    return {'file': str(args.out), 'duration': report['duration'], 'totalFrames': report['totalFrames'], 'shots': len(shots), 'cues': len(cues), 'maxFrameRoundingErrorMs': report['cueMaxRoundingErrorMs']}


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    a = sub.add_parser('analyze')
    a.add_argument('--music', type=Path, required=True)
    a.add_argument('--out', type=Path, required=True)
    a.add_argument('--offset', type=float, default=0)
    a.add_argument('--seconds', type=float, default=50)
    a.add_argument('--bpm', type=float)
    a.add_argument('--first-beat', type=float)
    a.add_argument('--ffmpeg')
    a.set_defaults(handler=analyze)
    b = sub.add_parser('plan')
    b.add_argument('--grid', type=Path, required=True)
    b.add_argument('--story', type=Path, required=True)
    b.add_argument('--out', type=Path, required=True)
    b.add_argument('--snap-onsets', action='store_true')
    b.set_defaults(handler=plan)
    args = parser.parse_args()
    try:
        print(json.dumps(args.handler(args), ensure_ascii=False))
    except (ValueError, OSError, RuntimeError, subprocess.TimeoutExpired, KeyError, ImportError) as error:
        parser.exit(1, str(error)[:1500] + '\n')


if __name__ == '__main__':
    main()
