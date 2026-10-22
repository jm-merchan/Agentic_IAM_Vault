"""Prevent obsolete UI screenshots and broken notebook/document navigation."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location('workspace_documentation', Path(__file__).resolve().parents[2] / 'scripts/manual/validate.py')
docs = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(docs)


def write(root, name, content):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def test_current_guides_reject_historical_inline_images_but_preserve_reports(tmp_path):
    write(tmp_path, 'docs/runs/old/screenshots/ui.png', 'image')
    write(tmp_path, 'README.md', '![UI](docs/runs/old/screenshots/ui.png)')
    write(tmp_path, 'docs/E2E_VERIFICATION.md', '![Historic](runs/old/screenshots/ui.png)')
    report = docs.validate(tmp_path)
    assert len(report['errors']) == 1
    assert 'README.md: outdated embedded screenshot' in report['errors'][0]
    write(tmp_path, 'README.md', '[Historic screenshot](docs/runs/old/screenshots/ui.png)')
    assert docs.validate(tmp_path)['all_passed']


def test_notebook_markdown_is_validated(tmp_path):
    write(tmp_path, 'example.ipynb', json.dumps({'nbformat': 4, 'cells': [
        {'cell_type': 'markdown', 'source': ['![Missing](missing.png)']},
    ]}))
    assert any('missing.png' in error for error in docs.validate(tmp_path)['errors'])


def test_links_validate_heading_anchors_and_skip_code_examples(tmp_path):
    write(tmp_path, 'guide.md', '# Guía de instalación\n## Paso\n## Paso\n')
    write(tmp_path, 'README.md', '[OK](guide.md#guía-de-instalación)\n[Duplicate](guide.md#paso-1)\n```text\n[example](absent.md)\n```\n')
    assert docs.validate(tmp_path)['all_passed']
    write(tmp_path, 'README.md', '[Stale title](guide.md#old-title)')
    assert any('missing anchor' in error for error in docs.validate(tmp_path)['errors'])


@pytest.mark.parametrize('problem', ['missing_manifest', 'missing_provenance', 'changed_image', 'missing_image', 'duplicate'])
def test_screenshot_provenance_is_checked(tmp_path, problem):
    image = write(tmp_path, 'docs/screenshots/current/ui.png', 'image')
    entry = {'file': 'ui.png', 'description': 'UI', 'url': 'http://localhost:8088/',
             'captured_at': '2026-10-22T14:00:00Z', 'sha256': hashlib.sha256(image.read_bytes()).hexdigest()}
    if problem == 'missing_provenance':
        entry.pop('captured_at')
    if problem == 'changed_image':
        image.write_text('different capture')
    entries = [entry]
    if problem == 'missing_image':
        entries.append({**entry, 'file': 'absent.png'})
    if problem == 'duplicate':
        entries.append(entry)
    if problem != 'missing_manifest':
        write(tmp_path, 'docs/screenshots/current/manifest.json', json.dumps({'captures': entries}))
    assert not docs.validate(tmp_path)['all_passed']
