"""Validate workspace docs and source syntax without executing installation code."""
from datetime import datetime, timezone
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]


def bash_blocks(path):
    return re.findall(r'^```bash\n(.*?)^```', path.read_text(), re.M | re.S)


def markdown_content(text):
    """Ignore literal examples when checking rendered Markdown links/headings."""
    return re.sub(r'^```[^\n]*\n.*?^```\s*$', '', text, flags=re.M | re.S)


def anchors(text):
    found = set(re.findall(r'<(?:a|h[1-6])\b[^>]*(?:id|name)=[\"\']([^\"\']+)', text))
    counts = {}
    for heading in re.findall(r'^#{1,6}\s+(.+?)\s*#*$', markdown_content(text), re.M):
        heading = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', heading)
        slug = re.sub(r'[^\w\-\s]', '', re.sub(r'<[^>]+>', '', heading).lower())
        slug = re.sub(r'\s', '-', slug)
        number = counts.get(slug, 0)
        counts[slug] = number + 1
        found.add(slug if number == 0 else f'{slug}-{number}')
    return found


def current_guide(path, root):
    relative = path.relative_to(root).as_posix()
    if relative.startswith(('verify/', 'okta/', 'docs/runs/')):
        return False
    return relative not in {'docs/E2E_VERIFICATION.md', 'docs/E2E_OPENAI_VERIFICATION.md',
                            'docs/WORKSPACE_REVIEW.md', 'docs/manual/VALIDACION.md'}


def check_links(text, path, root, errors):
    checked = 0
    for bang, target in re.findall(r'(!?)\[[^\]]*\]\(([^)]+)\)', markdown_content(text)):
        target = target.strip('<>')
        parsed = urlsplit(target)
        if parsed.scheme:
            continue
        checked += 1
        destination = (path.parent / unquote(parsed.path)).resolve() if parsed.path else path
        if not destination.is_file() and not destination.is_dir():
            errors.append(f'{path.relative_to(root)}: missing link {target}')
            continue
        if parsed.fragment and destination.suffix == '.md':
            if unquote(parsed.fragment) not in anchors(destination.read_text()):
                errors.append(f'{path.relative_to(root)}: missing anchor {target}')
        if bang and 'screenshots' in destination.parts and current_guide(path, root):
            if destination.parent != root / 'docs/screenshots/current':
                errors.append(f'{path.relative_to(root)}: outdated embedded screenshot {target}; use docs/screenshots/current')
    return checked


def check_screenshots(root, errors):
    folder = root / 'docs/screenshots/current'
    images = sorted(path for path in folder.iterdir() if path.suffix in {'.png', '.jpg', '.jpeg'}) if folder.is_dir() else []
    if not images:
        return 0
    try:
        manifest = json.loads((folder / 'manifest.json').read_text())
        entries = {entry['file']: entry for entry in manifest['captures']}
        if len(entries) != len(manifest['captures']):
            errors.append('screenshots/current: duplicate manifest entries')
        for path in images:
            entry = entries.get(path.name, {})
            if not all(entry.get(key) for key in ('description', 'captured_at', 'url', 'sha256')):
                errors.append(f'screenshots/current/{path.name}: missing capture provenance')
            if entry.get('sha256') and hashlib.sha256(path.read_bytes()).hexdigest() != entry['sha256']:
                errors.append(f'screenshots/current/{path.name}: digest differs from manifest')
        for name in entries:
            if not (folder / name).is_file():
                errors.append(f'screenshots/current/{name}: manifest file missing')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        errors.append(f'screenshots/current: invalid manifest: {exc}')
    return len(images)


def validate(root=ROOT):
    errors = []
    document_folders = ('', 'docs', 'docs/manual', 'chatbot', 'verify', 'okta', 'okta/docs',
                        'chatbot/static/service-icons', 'docs/screenshots')
    documents = sorted(path for folder in document_folders for path in (root / folder).glob('*.md'))
    count = links = 0
    for path in documents:
        for index, block in enumerate(bash_blocks(path), 1):
            count += 1
            result = subprocess.run(['bash', '-n'], input=block, text=True, capture_output=True)
            if result.returncode:
                errors.append(f'{path.name} block {index}: {result.stderr.strip()}')
        links += check_links(path.read_text(), path, root, errors)
    screenshots = check_screenshots(root, errors)
    # Include the executable files used by the guided installer and their shell
    # helpers, not just the scripts that extract the historical Markdown blocks.
    script_folders = ('', 'scripts', 'scripts/manual', 'scripts/demo', 'verify/scripts', 'chatbot/scripts', 'okta/scripts')
    scripts = sorted(path for folder in script_folders
                     for path in (root / folder).glob('*.sh'))
    for path in scripts:
        result = subprocess.run(['bash', '-n', str(path)], text=True, capture_output=True)
        if result.returncode:
            errors.append(f'{path.name}: {result.stderr.strip()}')
        # Quoted Python heredocs contain literal source, independent of Bash.
        for source in re.findall(r"<<'PY'\n(.*?)^PY$", path.read_text(), re.M | re.S):
            try:
                ast.parse(source)
            except SyntaxError as exc:
                errors.append(f'{path.name}: embedded Python: {exc}')
    python_files = sorted(path for folder in (*script_folders, 'chatbot/app', 'chatbot/tests')
                          for path in (root / folder).glob('*.py'))
    for path in python_files:
        try:
            ast.parse(path.read_text())
        except SyntaxError as exc:
            errors.append(f'{path.relative_to(root)}: {exc}')
    notebooks = sorted(path for folder in ('', 'verify', 'okta') for path in (root / folder).glob('*.ipynb'))
    bash_cells = 0
    for path in notebooks:
        try:
            notebook = json.loads(path.read_text())
            if notebook.get('nbformat') != 4 or not isinstance(notebook.get('cells'), list):
                raise ValueError('expected nbformat 4 and a cells array')
            for index, cell in enumerate(notebook['cells'], 1):
                if cell.get('cell_type') == 'markdown':
                    links += check_links(''.join(cell.get('source', [])), path, root, errors)
                    continue
                if cell.get('cell_type') != 'code':
                    continue
                if cell.get('outputs') or cell.get('execution_count') is not None:
                    errors.append(f'{path.name} cell {index}: saved execution output/count')
                source = ''.join(cell.get('source', []))
                if source.startswith('%%bash\n'):
                    bash_cells += 1
                    result = subprocess.run(['bash', '-n'], input=source[7:], text=True, capture_output=True)
                    if result.returncode:
                        errors.append(f'{path.name} cell {index}: {result.stderr.strip()}')
        except (ValueError, TypeError, AttributeError) as exc:
            errors.append(f'{path.name}: invalid notebook: {exc}')
    return {'checked_at': datetime.now(timezone.utc).isoformat(), 'documents': len(documents),
            'bash_blocks': count, 'shell_scripts': len(scripts), 'local_links': links,
            'python_files': len(python_files), 'notebooks': len(notebooks), 'bash_cells': bash_cells, 'current_screenshots': screenshots,
            'errors': errors, 'all_passed': not errors,
            'scope': 'Static syntax, local links/anchors, notebook Markdown and screenshot provenance only. No provisioning, credentials issuance, inference, revocation or deletion.'}


if __name__ == '__main__':
    report = validate()
    (ROOT / 'docs/manual/validacion.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report['all_passed'] else 1)
