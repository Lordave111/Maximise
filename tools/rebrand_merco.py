from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {'.git', '.github', '.venv', 'venv', '__pycache__', 'node_modules'}
BINARY_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.ico', '.woff', '.woff2', '.ttf', '.otf', '.pdf', '.zip', '.pyc'}

for path in ROOT.rglob('*'):
    if not path.is_file() or any(part in SKIP_DIRS for part in path.parts):
        continue
    if path.suffix.lower() in BINARY_EXTENSIONS:
        continue
    try:
        text = path.read_text(encoding='utf-8')
    except (UnicodeDecodeError, OSError):
        continue
    updated = text.replace('MAXIMISE', 'MERCO').replace('Maximise', 'Merco')
    if updated != text:
        path.write_text(updated, encoding='utf-8')
        print(f'Rebranded {path.relative_to(ROOT)}')
