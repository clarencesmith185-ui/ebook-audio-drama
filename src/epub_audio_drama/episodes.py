"""Lossless, source-bound episode export from existing speech renders (no GPU)."""
import hashlib
import math
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import wave

from .core import ContractError, canonical_hash, digest, inside, load, rendering_units, save, text_check


def sentence_end(text):
    """Conservative text heuristic, not word-level alignment or listening approval."""
    tail = text.rstrip().rstrip('\"\'”’」』）)]').rstrip()
    if not re.search(r'[.!?。！？]$', tail) or tail.endswith(('...', '…')):
        return False
    # Avoid common English abbreviation/initial boundaries. Ambiguous cases stay joined.
    if re.search(r'\b(?:Mr|Mrs|Ms|Dr|Prof|Sr|Jr|St|vs|etc|e\.g|i\.e)\.$', tail, re.I):
        return False
    return not re.search(r'\b[A-Za-z]\.$', tail)


def choose_cuts(candidates, frames, target):
    """Balance parts around target length, including the tail; never invent a cut."""
    ratio = min(len(candidates) + 1, frames / target)
    count = max(1, int(ratio + .5))
    cuts = []
    start = 0
    for i in range(1, count):
        # Reserve enough distinct candidates for remaining boundaries.
        stop = len(candidates) - (count - 1 - i)
        j = min(range(start, stop), key=lambda j: abs(candidates[j][0] - frames * i / count))
        cuts.append(candidates[j])
        start = j + 1
    return cuts


def export(root, chapter, run, output, episode_minutes, mp3=False):
    if not math.isfinite(episode_minutes) or episode_minutes <= 0:
        raise ContractError('--episode-minutes must be finite and greater than zero')
    root, run, output = Path(root), Path(run), Path(output)
    if output.exists():
        raise ContractError('Episode output already exists; choose a new directory')
    if mp3 and not shutil.which('ffmpeg'):
        raise ContractError('MP3 export requires ffmpeg')
    script = load(inside(root, f'chapters/{chapter}/script.json'))
    source = inside(root, f'chapters/{chapter}/source.txt').read_text(encoding='utf-8')
    text_check(source, script)
    report = load(run / 'report.json')
    config = report['config']
    binding = config['binding']
    if (binding['source_sha256'] != digest(source.encode()) or
            binding['script_sha256'] != canonical_hash(script)):
        raise ContractError('Render source/script binding changed')
    master = run / 'chapter.wav'
    if digest(master.read_bytes()) != report['audio_sha256']:
        raise ContractError('Chapter master hash mismatch')
    units = rendering_units(script)
    records = report['segments']
    if len(units) != len(records) or not units:
        raise ContractError('Incomplete render segment coverage')
    candidates = []
    expected_pcm = hashlib.sha256()
    with wave.open(str(master), 'rb') as wav:
        params = wav.getparams()
        rate, frames = wav.getframerate(), wav.getnframes()
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2 or wav.getcomptype() != 'NONE':
            raise ContractError('Episode export requires the renderer mono PCM16 master')
        gap = int(rate * config['gap_seconds'])
        if gap <= 0:
            raise ContractError('Render has no inter-unit pauses')
        cursor = 0
        for i, (unit, record) in enumerate(zip(units, records)):
            path = inside(run, record['file'])
            meta = load(path.with_suffix('.json'))
            voice = record['voice']
            expected_signature = canonical_hash({'segment': unit, 'voice': binding['voices'][voice], 'config': config})
            if (record['index'] != i or meta['signature'] != expected_signature or
                    digest(path.read_bytes()) != meta['audio_sha256']):
                raise ContractError('Segment checkpoint binding/hash mismatch')
            with wave.open(str(path), 'rb') as segment:
                if (segment.getnchannels(), segment.getsampwidth(), segment.getframerate(), segment.getcomptype()) != (1, 2, rate, 'NONE'):
                    raise ContractError('Segment audio format mismatch')
                size = segment.getnframes()
                if size <= 0:
                    raise ContractError('Empty segment audio')
                while data := segment.readframes(65536):
                    if wav.readframes(len(data) // 2) != data:
                        raise ContractError('Master differs from retained segment audio')
                    expected_pcm.update(data)
            silence = bytes(gap * 2)
            if wav.readframes(gap) != silence:
                raise ContractError('Master inter-unit pause differs from render configuration')
            expected_pcm.update(silence)
            cursor += size + gap
            if i < len(units) - 1 and sentence_end(source[max(0, unit['end']-200):unit['end']]):
                candidates.append((cursor - gap + gap // 2, unit['end']))
        if cursor != frames:
            raise ContractError('Master frame coverage mismatch')
    cuts = choose_cuts(candidates, frames, episode_minutes * 60 * rate)
    boundaries = [(0, 0), *cuts, (frames, len(source))]
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.episodes-', dir=output.parent))
    try:
        parts = []
        actual_pcm = hashlib.sha256()
        with wave.open(str(master), 'rb') as wav:
            for i, ((start, text_start), (end, text_end)) in enumerate(zip(boundaries, boundaries[1:]), 1):
                path = staging / f'episode-{i:03d}.wav'
                with wave.open(str(path), 'wb') as part:
                    part.setparams(params)
                    wav.setpos(start)
                    remaining = end - start
                    while remaining:
                        data = wav.readframes(min(remaining, 65536))
                        if not data:
                            raise ContractError('Unexpected end of master')
                        part.writeframesraw(data)
                        remaining -= len(data) // 2
                with wave.open(str(path), 'rb') as part:
                    while data := part.readframes(65536):
                        actual_pcm.update(data)
                item = dict(file=path.name, start_frame=start, end_frame=end,
                            duration_seconds=(end-start)/rate, source_start=text_start, source_end=text_end,
                            sha256=digest(path.read_bytes()))
                if mp3:
                    encoded = path.with_suffix('.mp3')
                    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-i', str(path),
                                    '-codec:a', 'libmp3lame', '-b:a', '96k', str(encoded)], check=True)
                    item.update(mp3=encoded.name, mp3_sha256=digest(encoded.read_bytes()))
                parts.append(item)
        if actual_pcm.digest() != expected_pcm.digest():
            raise ContractError('Exported PCM reconstruction failed')
        save(staging / 'episodes.json', dict(target_minutes=episode_minutes, sample_rate=rate,
             source_sha256=binding['source_sha256'], script_sha256=binding['script_sha256'],
             master_sha256=report['audio_sha256'], pcm_sha256=actual_pcm.hexdigest(),
             pcm_reconstruction='PASS', parts=parts,
             boundary_policy='Sentence-ending text heuristic at existing inter-unit pause midpoints; balanced lengths, not a hard cap.',
             listening_status='NOT VERIFIED; export does not establish audible word accuracy',
             mp3_note='Lossy convenience copies; PCM preservation applies to WAV parts only.'))
        staging.rename(output)
    except BaseException:
        shutil.rmtree(staging)
        raise
    return output
