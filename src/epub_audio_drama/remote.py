"""Opt-in Kaggle execution via the official CLI; credentials stay in its environment."""
import json
import os
import re
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from .core import ContractError, digest, load, save

OWNER = re.compile(r'[a-z0-9_-]+')
OUTPUT_PATTERN = r'.*\.(?:wav|flac|mp3|json|txt|log)$'


def configuration(project=None):
    """Only non-secret execution preferences belong in project/execution.json."""
    path = Path(project) / 'execution.json' if project else None
    config = load(path) if path and path.exists() else {}
    if set(config) - {'backend', 'kaggle'}:
        raise ContractError('execution.json accepts only backend and kaggle preferences; never credentials')
    if config.get('backend', 'local') not in ('local', 'kaggle'):
        raise ContractError('Execution backend must be local or kaggle')
    if not isinstance(config.get('kaggle', {}), dict) or set(config.get('kaggle', {})) - {'owner'}:
        raise ContractError('kaggle configuration accepts only owner; set credentials in the environment')
    return config


def backend(project, override=None):
    return override or configuration(project).get('backend', 'local')


def credentials_available():
    folder = Path(os.environ.get('KAGGLE_CONFIG_DIR', str(Path.home() / '.kaggle')))
    return bool(os.environ.get('KAGGLE_API_TOKEN') or
                (os.environ.get('KAGGLE_USERNAME') and os.environ.get('KAGGLE_KEY')) or
                (folder / 'access_token').is_file() or (folder / 'kaggle.json').is_file())


def cli(arguments):
    if not credentials_available():
        raise ContractError('Set KAGGLE_API_TOKEN (or legacy KAGGLE_USERNAME/KAGGLE_KEY or Kaggle credential file) before using Kaggle')
    try:
        # No shell, secret command arguments, environment serialization or raw errors.
        result = subprocess.run(['kaggle', *arguments], capture_output=True, text=True, timeout=180)
    except FileNotFoundError:
        raise ContractError('Kaggle CLI not found; install ebook-audio-drama[kaggle]') from None
    except subprocess.TimeoutExpired:
        raise ContractError('Kaggle request timed out; remote state may be unknown. Inspect the receipt before retrying') from None
    if result.returncode:
        raise ContractError('Kaggle CLI request failed; check authentication, account/GPU eligibility and connectivity. Raw provider output suppressed to protect credentials')
    return result.stdout


def run(kind, project=None, chapter=None, plan=None, owner=None, run_dir=None,
        design_missing=False, reference_kernel=None):
    """Explicit upload command; unique notebook per run prevents version overwrites."""
    if not credentials_available():
        raise ContractError('Set KAGGLE_API_TOKEN or supported legacy credentials before launching')
    config = configuration(project)
    owner = owner or config.get('kaggle', {}).get('owner') or os.environ.get('KAGGLE_USERNAME')
    if not owner or not OWNER.fullmatch(owner):
        raise ContractError('Set --owner or execution.json kaggle.owner to your lowercase Kaggle username (tokens do not provide notebook names)')
    if kind not in ('speech', 'sound'):
        raise ContractError('Unknown Kaggle run kind')
    run_id = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S') + '-' + uuid.uuid4().hex[:12]
    slug = f'{owner}/ead-{kind}-{run_id}'
    base = Path(run_dir).expanduser() if run_dir else Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))) / 'ebook-audio-drama' / run_id
    if base.exists() and any(base.iterdir()):
        raise ContractError('Run directory must be new and empty; never overwrite a prior run')
    base.mkdir(parents=True, exist_ok=True)
    payload = base / 'payload'
    if kind == 'speech':
        from .kaggle import package
        package(project, chapter, slug, payload, reference_kernel, design_missing)
    else:
        from .sound import package
        package(plan, slug, payload)
    code_path = payload / 'run.py'
    marker = {'run_id': run_id, 'kind': kind, 'slug': slug}
    # Written only after the renderer succeeds. Distinguishes our run even when a
    # CLI version's output endpoint silently returns the latest notebook version.
    code = code_path.read_text() + '\nfrom pathlib import Path\nPath("/kaggle/working/remote-run.json").write_text(' + repr(json.dumps(marker)) + ')\n'
    if len(code.encode()) >= 1_000_000:
        raise ContractError('Kaggle source exceeds 1 MB; use a reference kernel')
    compile(code, 'run.py', 'exec')
    code_path.write_text(code)
    manifest = load(payload / 'payload-manifest.json')
    manifest['executed_source_sha256'] = digest(code.encode())
    manifest['run_marker'] = marker
    save(payload / 'payload-manifest.json', manifest)
    receipt_path = base / 'receipt.json'
    receipt = dict(marker, state='PREPARED', source_sha256=digest(code.encode()),
                   metadata_sha256=digest((payload / 'kernel-metadata.json').read_bytes()),
                   payload=str(payload.resolve()), version=None,
                   status_scope='latest notebook session, not version-specific')
    save(receipt_path, receipt)
    # Persist uncertainty before upload: a timeout must not look safe to retry.
    receipt['state'] = 'PUSH_REQUESTED'; save(receipt_path, receipt)
    try:
        output = cli(['kernels', 'push', '-p', str(payload.resolve())])
    except ContractError:
        receipt['state'] = 'PUSH_UNCONFIRMED'; save(receipt_path, receipt)
        raise ContractError(f'Kaggle launch not confirmed; inspect {receipt_path} and the notebook before retrying') from None
    # Do not persist raw output: CLI/provider messages might contain secrets.
    url = re.search(r'https://www\.kaggle\.com/code/([a-z0-9_-]+/[a-z0-9-]+)(?:/([0-9]+)|\?scriptVersionId=([0-9]+))?', output)
    version = re.search(r'\bversion\s+(\d+)\b', output, re.I)
    if url and url.group(1) != slug:
        receipt['state'] = 'DESTINATION_MISMATCH'; save(receipt_path, receipt)
        raise ContractError(f'Kaggle returned a different destination; inspect {receipt_path} before any further action')
    receipt.update(state='SUBMITTED' if url else 'PUSH_UNCONFIRMED',
                   version=int(version.group(1)) if version else (int(url.group(2)) if url and url.group(2) else None),
                   url=f'https://www.kaggle.com/code/{slug}')
    save(receipt_path, receipt)
    return receipt_path


def receipt(path):
    data = load(path)
    if not re.fullmatch(r'[a-z0-9_-]+/[a-z0-9-]+', data['slug']) or not re.fullmatch(r'[0-9]{14}-[a-f0-9]{12}', data['run_id']):
        raise ContractError('Invalid run receipt')
    return data


def status(path):
    data = receipt(path)
    output = cli(['kernels', 'status', data['slug']])
    match = re.search(r'\b(complete|running|queued|error|cancelled|canceled)\b', output, re.I)
    state = match.group(1).upper() if match else 'UNKNOWN'
    data['latest_status'] = state
    data['checked_at'] = datetime.now(timezone.utc).isoformat()
    save(path, data)
    return {'status': state, 'scope': data['status_scope'], 'receipt': str(path)}


def download(path, destination=None):
    data = receipt(path)
    if status(path)['status'] != 'COMPLETE':
        raise ContractError('Notebook is not COMPLETE; wait or inspect the Kaggle run')
    out = Path(destination) if destination else Path(path).parent / 'output'
    if out.exists() and any(out.iterdir()):
        raise ContractError('Download destination must be new and empty')
    out.mkdir(parents=True, exist_ok=True)
    # No version suffix claim: cross-check a run-specific marker instead.
    cli(['kernels', 'output', data['slug'], '-p', str(out.resolve()), '--file-pattern', OUTPUT_PATTERN])
    markers = list(out.rglob('remote-run.json'))
    if len(markers) != 1 or load(markers[0]) != {k: data[k] for k in ('run_id', 'kind', 'slug')}:
        raise ContractError('Downloaded output is not bound to this run; preserve it for inspection, do not import or mix')
    files = {str(p.relative_to(out)): digest(p.read_bytes()) for p in out.rglob('*') if p.is_file()}
    if not any(name.endswith(('.wav', '.flac', '.mp3')) for name in files):
        raise ContractError('No audio found in downloaded output; do not treat this as a successful render')
    data = receipt(path)
    data.update(state='DOWNLOADED', output=str(out.resolve()), output_hashes=files,
                output_binding='run marker verified; audio quality and per-asset contracts still require review')
    save(path, data)
    return out
