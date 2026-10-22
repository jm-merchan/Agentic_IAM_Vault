"""Validate workspace docs and source syntax without executing installation code."""
from datetime import datetime, timezone
import ast
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]


def bash_blocks(path):
    return re.findall(r'^```bash\n(.*?)^```', path.read_text(), re.M | re.S)


def validate(root=ROOT):
    errors = []
    document_folders = ('', 'docs', 'docs/manual', 'chatbot', 'verify', 'okta', 'okta/docs',
                        'chatbot/static/service-icons')
    documents = sorted(path for folder in document_folders for path in (root / folder).glob('*.md'))
    count = links = 0
    for path in documents:
        for index, block in enumerate(bash_blocks(path), 1):
            count += 1
            result = subprocess.run(['bash', '-n'], input=block, text=True, capture_output=True)
            if result.returncode:
                errors.append(f'{path.name} block {index}: {result.stderr.strip()}')
        for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)', path.read_text()):
            target = target.strip('<>')
            if urlsplit(target).scheme or target.startswith('#'):
                continue
            links += 1
            if not (path.parent / unquote(target.split('#', 1)[0])).exists():
                errors.append(f'{path.name}: missing link {target}')
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
            'python_files': len(python_files), 'notebooks': len(notebooks), 'bash_cells': bash_cells,
            'errors': errors, 'all_passed': not errors,
            'scope': 'Static syntax and local links only. No provisioning, credentials issuance, inference, revocation or deletion.'}


if __name__ == '__main__':
    report = validate()
    (ROOT / 'docs/manual/validacion.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report['all_passed'] else 1)
