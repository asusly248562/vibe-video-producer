"""Portable regression tests. All artifacts are synthetic and live in temporary projects."""
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import wave
import zlib
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
FF = os.environ.get('VIBE_FFMPEG') or shutil.which('ffmpeg')
NODE = os.environ.get('VIBE_NODE') or shutil.which('node')


def command(args, ok=True):
    env = os.environ.copy()
    env.update(PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1')
    result = subprocess.run(list(map(str, args)), capture_output=True, env=env, timeout=90)
    if (result.returncode == 0) != ok:
        raise AssertionError((result.returncode, (result.stdout + result.stderr)[-1800:].decode('utf-8', 'replace')))
    return result.stdout.decode('utf-8', 'replace')


def script(name, *args, ok=True):
    return command([sys.executable, ROOT / 'scripts' / name, *args], ok)


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    return path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def png(path, width, height):
    def chunk(kind, payload):
        return struct.pack('>I', len(payload)) + kind + payload + struct.pack('>I', zlib.crc32(kind + payload) & 0xffffffff)
    path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress((b'\x00' + b'\x08\x11\x18' * width) * height)) + chunk(b'IEND', b''))


class ProjectFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='vibe-skill-test-')
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.project = Path(json.loads(script('create_project.py', '--workspace', self.work, '--slug', 'synthetic', '--topic', '合成测试主题'))['project'])

    def record(self, kind, path, ok=True):
        return script('project_state.py', 'record', '--project', self.project, '--kind', kind, '--path', path, ok=ok)

    def status(self, scope='full'):
        return json.loads(script('project_state.py', 'status', '--project', self.project, '--scope', scope))


class WorkflowTests(ProjectFixture):
    def test_project_isolation_and_unicode(self):
        second = Path(json.loads(script('create_project.py', '--workspace', self.work, '--slug', 'synthetic', '--topic', '另一个主题'))['project'])
        self.assertNotEqual(self.project, second)
        self.assertEqual(json.loads((self.project / 'project.json').read_text(encoding='utf-8'))['topic'], '合成测试主题')

    def test_frame_plan_and_invalid_inputs(self):
        grid = write(self.work / 'grid.json', {'bpm': 112.5, 'sourceOffset': .4, 'beatTimes': [i * 8 / 15 for i in range(18)]})
        story = write(self.work / 'story.json', {'fps': 30, 'scenes': [{'id': 'a', 'beats': 4}, {'id': 'b', 'beats': 4, 'events': [{'id': 'formula', 'beat': 1.5}]}]})
        output = self.work / 'plan.json'
        script('beat_plan.py', 'plan', '--grid', grid, '--story', story, '--out', output)
        plan = json.loads(output.read_text(encoding='utf-8'))
        self.assertEqual(plan['shots'][0]['endFrame'], plan['shots'][1]['startFrame'])
        self.assertEqual(plan['shots'][1]['startFrame'], 64)
        self.assertLessEqual(plan['cueMaxRoundingErrorMs'], 1000 / 60 + 1e-6)
        for bad in [True, float('nan'), '0.5']:
            invalid = write(self.work / 'invalid.json', {'bpm': 120, 'sourceOffset': 0, 'beatTimes': [0, bad, 1]})
            script('beat_plan.py', 'plan', '--grid', invalid, '--story', story, '--out', output, ok=False)
        bad_story = write(self.work / 'bad-story.json', {'scenes': [{'id': 'x', 'beats': 100}]})
        script('beat_plan.py', 'plan', '--grid', grid, '--story', bad_story, '--out', output, ok=False)

    def test_partial_scope_and_modified_cover(self):
        horizontal, vertical = self.project / 'covers/h.png', self.project / 'covers/v.png'
        png(horizontal, 40, 30)
        png(vertical, 30, 40)
        self.record('cover-4x3', horizontal)
        self.assertTrue(self.status('cover-4x3')['readyToDeliver'])
        self.assertFalse(self.status('covers')['readyToDeliver'])
        self.record('cover-3x4', vertical)
        self.assertTrue(self.status('covers')['readyToDeliver'])
        self.assertFalse(self.status('full')['readyToDeliver'])
        png(horizontal, 44, 33)
        self.assertFalse(self.status('covers')['readyToDeliver'])
        self.record('cover-4x3', vertical, ok=False)

    def test_outside_file_rejected(self):
        external = self.work / 'outside.md'
        external.write_text('test fixture', encoding='utf-8')
        self.record('publish', external, ok=False)
        self.assertEqual(self.status('copy')['registeredArtifacts'], 0)

    def test_video_presence_is_not_completion(self):
        video = self.project / 'final/synthetic.mp4'
        video.write_bytes(b'synthetic non-video fixture')
        self.record('video', video)
        result = self.status('video')
        self.assertFalse(result['readyToDeliver'])
        self.assertIn('render-audit', result['missing'])
        self.assertIn('visual-review', result['missing'])

    @unittest.skipUnless(NODE, 'Node is not available')
    def test_clock_boundaries(self):
        command([NODE, ROOT / 'tests' / 'test_clock.cjs'])


@unittest.skipUnless(FF, 'FFmpeg is not available; set VIBE_FFMPEG to enable media integration')
class MediaIntegrationTests(ProjectFixture):
    def test_synthetic_audio_audit_and_bound_project(self):
        import numpy as np
        sr = 22050
        audio = np.zeros(sr * 12)
        rng = np.random.default_rng(52)
        for index, start in enumerate(np.arange(.25, 11.8, .5)):
            t = np.arange(int(.07 * sr)) / sr
            click = (.65 * np.sin(2 * np.pi * 85 * t) + rng.normal(0, .13, len(t))) * np.exp(-75 * t)
            i = round(start * sr)
            audio[i:i + len(click)] += click * (1 if index % 4 == 0 else .8)
        music = self.work / 'synthetic.wav'
        with wave.open(str(music), 'wb') as stream:
            stream.setparams((1, 2, sr, 0, 'NONE', 'not compressed'))
            stream.writeframes((audio * 24000).astype('<i2').tobytes())
        self.project = Path(json.loads(script('create_project.py', '--workspace', self.work, '--slug', 'media', '--topic', '合成音视频测试', '--music', music, '--width', '160', '--height', '90'))['project'])
        grid = self.project / 'beat-grid.json'
        measurement = json.loads(script('beat_plan.py', 'analyze', '--music', music, '--out', grid, '--seconds', '10', '--ffmpeg', FF))
        self.assertLess(abs(measurement['bpm'] - 120), 1)
        script('beat_plan.py', 'analyze', '--music', music, '--out', grid, '--seconds', '10', '--ffmpeg', FF, '--bpm', '120', '--first-beat', '.25')
        story = write(self.project / 'storyboard.json', {'fps': 30, 'scenes': [{'id': 'a', 'beats': 4}, {'id': 'b', 'beats': 4, 'events': [{'id': 'formula', 'beat': 2}]}]})
        plan = self.project / 'beat-map.json'
        script('beat_plan.py', 'plan', '--grid', grid, '--story', story, '--out', plan)
        score = self.project / 'assets/score.m4a'
        command([FF, '-v', 'error', '-y', '-ss', '0.25', '-i', music, '-t', '4', '-c:a', 'aac', score])
        video = self.project / 'final/video.mp4'
        command([FF, '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=0x081118:s=160x90:r=30:d=4', '-i', score, '-t', '4', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', video])
        audit = self.project / 'verification/render-audit.json'
        args = ['--video', video, '--plan', plan, '--score', score, '--width', '160', '--height', '90', '--ffmpeg', FF]
        script('audit_render.py', *args, '--out', audit)
        sources = self.project / 'sources.md'
        sources.write_text('Synthetic mathematical test pattern; no real-world claim.', encoding='utf-8')
        cues = json.loads(plan.read_text(encoding='utf-8'))['cues']
        review = write(self.project / 'verification/visual-review.json', {'passed': True, 'fontsChecked': True, 'knowledgeChecked': True, 'videoSha256': sha(video), 'planSha256': sha(plan), 'sourcesSha256': sha(sources), 'storyboardSha256': sha(story), 'checkedFrames': [c['frame'] for c in cues], 'notes': 'Synthetic fixture for state gating, not a review of user media.'})
        for kind, path in [('sources', sources), ('storyboard', story), ('beat-map', plan), ('score', score), ('video', video), ('render-audit', audit), ('visual-review', review)]:
            self.record(kind, path)
        self.assertTrue(self.status('video')['readyToDeliver'])
        review_data = json.loads(review.read_text(encoding='utf-8'))
        review_data['checkedFrames'].pop()
        write(review, review_data)
        self.record('visual-review', review)
        self.assertFalse(self.status('video')['readyToDeliver'])
        sources.write_text('Changed source after review.', encoding='utf-8')
        self.record('sources', sources)
        self.assertTrue(any('bound' in issue['reason'] for issue in self.status('video')['invalid']))
        wrong = self.work / 'wrong-plan.json'
        data = json.loads(plan.read_text(encoding='utf-8'))
        data['totalFrames'] += 1
        write(wrong, data)
        script('audit_render.py', '--video', video, '--plan', wrong, '--width', '160', '--height', '90', '--ffmpeg', FF, '--out', self.work / 'wrong-audit.json', ok=False)
        delayed = self.work / 'delayed.m4a'
        command([FF, '-v', 'error', '-y', '-i', score, '-af', 'adelay=80:all=1', '-t', '4', '-c:a', 'aac', delayed])
        script('audit_render.py', '--video', video, '--plan', plan, '--score', delayed, '--width', '160', '--height', '90', '--ffmpeg', FF, '--out', self.work / 'delay-audit.json', ok=False)
        (self.project / 'assets/music-source.wav').write_bytes(b'changed fixture')
        self.assertTrue(any(i['kind'] == 'music-source' for i in self.status('video')['invalid']))


if __name__ == '__main__':
    unittest.main()
