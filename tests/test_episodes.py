import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave

from epub_audio_drama.core import ContractError, canonical_hash, digest, load, rendering_units, save
from epub_audio_drama.episodes import export, sentence_end


def write_wav(path, pcm, rate=1000):
    with wave.open(str(path), 'wb') as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(rate); f.writeframes(pcm)


def read_pcm(path):
    with wave.open(str(path), 'rb') as f:
        return f.readframes(f.getnframes())


class EpisodeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / 'project'
        self.run = self.root / 'run'
        self.run.mkdir()
        self.chapter = self.project / 'chapters/001'
        self.chapter.mkdir(parents=True)
        self.output = self.root / 'episodes'
        self.make_run(['One sentence. ', 'Second sentence! ', 'Last sentence.'])

    def make_run(self, texts):
        source = ''.join(texts)
        (self.chapter / 'source.txt').write_text(source)
        segments = []; start = 0
        for i, text in enumerate(texts):
            segments.append(dict(start=start, end=start+len(text), text=text, speaker=f'p{i}'))
            start += len(text)
        script = dict(source_sha256=digest(source.encode()), source_reviewed=True, segments=segments)
        save(self.chapter / 'script.json', script)
        binding = dict(source_sha256=script['source_sha256'], script_sha256=canonical_hash(script), voices={})
        config = dict(binding=binding, gap_seconds=.15)
        records = []; master = b''
        for i, unit in enumerate(rendering_units(script)):
            vid = f'v{i}'; binding['voices'][vid] = dict(character=unit['speaker'])
        for i, unit in enumerate(rendering_units(script)):
            vid = f'v{i}'; path = self.run / f'{i:05d}.wav'
            pcm = (i+1).to_bytes(2, 'little') * 1000
            write_wav(path, pcm)
            save(path.with_suffix('.json'), dict(signature=canonical_hash(dict(segment=unit, voice=binding['voices'][vid], config=config)), audio_sha256=digest(path.read_bytes())))
            records.append(dict(index=i, file=path.name, voice=vid))
            master += pcm + bytes(300)
        write_wav(self.run / 'chapter.wav', master)
        save(self.run / 'report.json', dict(config=config, segments=records, audio_sha256=digest((self.run / 'chapter.wav').read_bytes())))
        return master

    def test_lossless_partition_source_coverage_and_balanced_tail(self):
        original = read_pcm(self.run / 'chapter.wav')
        export(self.project, '001', self.run, self.output, .02)
        manifest = load(self.output / 'episodes.json')
        parts = manifest['parts']
        self.assertEqual(len(parts), 3)
        self.assertEqual(b''.join(read_pcm(self.output / p['file']) for p in parts), original)
        self.assertEqual(manifest['pcm_sha256'], hashlib.sha256(original).hexdigest())
        self.assertEqual([p['end_frame'] for p in parts], [1075, 2225, 3450])
        source = (self.chapter / 'source.txt').read_text()
        self.assertEqual(''.join(source[p['source_start']:p['source_end']] for p in parts), source)
        self.assertAlmostEqual(sum(p['duration_seconds'] for p in parts), 3.45)
        self.assertIn('NOT VERIFIED', manifest['listening_status'])

    def test_long_target_and_no_sentence_boundaries_keep_one_part(self):
        for texts, minutes in [(['Unfinished ', 'clause; ', 'ending'], .001), (['A. ', 'B. ', 'C.'], 20)]:
            self.make_run(texts)
            output = self.root / ('out' + str(minutes))
            export(self.project, '001', self.run, output, minutes)
            self.assertEqual(len(load(output / 'episodes.json')['parts']), 1)

    def test_bad_duration_and_existing_destination_rejected(self):
        for value in [0, -1, float('nan'), float('inf')]:
            with self.assertRaises(ContractError):
                export(self.project, '001', self.run, self.output, value)
        self.output.mkdir()
        with self.assertRaises(ContractError):
            export(self.project, '001', self.run, self.output, 10)

    def test_extremely_small_target_is_bounded_by_safe_cuts(self):
        export(self.project, '001', self.run, self.output, 1e-300)
        self.assertEqual(len(load(self.output / 'episodes.json')['parts']), 3)

    def test_tampered_master_source_or_checkpoint_fails_before_export(self):
        for target in ['master', 'script', 'checkpoint', 'pause']:
            self.make_run(['First sentence. ', 'Second sentence!'])
            if target == 'master':
                with (self.run / 'chapter.wav').open('ab') as f: f.write(b'changed')
            elif target == 'script':
                p = self.chapter / 'script.json'; s = load(p); s['source_reviewed'] = False; save(p, s)
            elif target == 'checkpoint':
                p = self.run / '00000.json'; s = load(p); s['signature'] = 'changed'; save(p, s)
            else:
                p = self.run / 'chapter.wav'; pcm = bytearray(read_pcm(p)); pcm[2100] = 1; write_wav(p, pcm)
                r = load(self.run / 'report.json'); r['audio_sha256'] = digest(p.read_bytes()); save(self.run / 'report.json', r)
            with self.assertRaises(ContractError, msg=target):
                export(self.project, '001', self.run, self.output, .02)
            self.assertFalse(self.output.exists())

    def test_sentence_heuristic_avoids_clause_chunk_and_abbreviation(self):
        for text in ['A long chunk', 'Wait, ', 'Mr. ', 'Dr. ', 'Wait... ', 'A. ', 'A clause;']:
            self.assertFalse(sentence_end(text), text)
        for text in ['He left. ', '“Go!” ', '走了。', '好嗎？」']:
            self.assertTrue(sentence_end(text), text)

    @unittest.skipUnless(shutil.which('ffmpeg'), 'ffmpeg absent')
    def test_cli_with_decodable_mp3(self):
        result = subprocess.run([sys.executable, '-m', 'epub_audio_drama.cli', 'episodes', str(self.project), '001', str(self.run), str(self.output), '--episode-minutes', '.02', '--mp3'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        for p in load(self.output / 'episodes.json')['parts']:
            subprocess.run(['ffmpeg', '-v', 'error', '-i', str(self.output / p['mp3']), '-f', 'null', '-'], check=True)
