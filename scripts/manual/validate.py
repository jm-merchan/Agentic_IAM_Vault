"""Validate manual links and Bash syntax without executing installation blocks."""
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
    documents = sorted((root / 'docs/manual').glob('*.md'))
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
    scripts = sorted(path for folder in ('scripts/manual', 'scripts/demo', 'verify/scripts', 'chatbot/scripts')
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
    for path in (root / 'scripts/manual').glob('*.py'):
        try:
            ast.parse(path.read_text())
        except SyntaxError as exc:
            errors.append(f'{path.name}: {exc}')
    return {'checked_at': datetime.now(timezone.utc).isoformat(), 'documents': len(documents),
            'bash_blocks': count, 'shell_scripts': len(scripts), 'local_links': links,
            'errors': errors, 'all_passed': not errors,
            'scope': 'Static syntax and local links only. No provisioning, credentials issuance, inference, revocation or deletion.'}


if __name__ == '__main__':
    report = validate()
    (ROOT / 'docs/manual/validacion.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report['all_passed'] else 1)
