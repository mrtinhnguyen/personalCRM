#!/usr/bin/env python3
"""Check the public working tree for common accidental private artifacts.

This deliberately reports paths/rule names, never matching secret values.
It complements manual review and a dedicated secret scanner.
"""
from pathlib import Path
import re
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
paths = subprocess.check_output(
    ['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], cwd=root,
).decode().split('\0')
rules = {
    'private-tailnet-host': re.compile(r'\b[\w.-]+\.tail[a-z0-9]+\.ts\.net\b', re.I),
    'personal-home-path': re.compile(r'/(?:Users|home)/[A-Za-z0-9_.-]+/'),
    'private-key': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'github-token': re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b'),
    'aws-access-key': re.compile(r'\bAKIA[A-Z0-9]{16}\b'),
}
blocked_suffixes = {'.db', '.sqlite', '.sqlite3', '.dump', '.pem', '.key', '.p12', '.log', '.zip', '.tar', '.gz'}
problems = []
for relative in filter(None, paths):
    path = root / relative
    if not path.is_file():
        continue
    if path.is_symlink():
        problems.append((relative, 'symlink requires explicit review'))
        continue
    if (path.name.startswith('.env') and path.name != '.env.example') or path.suffix in blocked_suffixes:
        problems.append((relative, 'private artifact type'))
    if any(part in {'data', 'runtime', 'backups', 'exports', 'secrets', '.local-validation', 'volumes'} for part in path.relative_to(root).parts):
        problems.append((relative, 'private artifact directory'))
    raw = path.read_bytes()
    if b'\0' in raw:
        if path.suffix not in {'.png', '.jpg', '.jpeg', '.webp', '.ico'}:
            problems.append((relative, 'unexpected binary file'))
        continue
    source = raw.decode('utf-8', errors='replace')
    for label, pattern in rules.items():
        if pattern.search(source):
            problems.append((relative, label))
if problems:
    for path, rule in problems:
        print(f'{path}: {rule}')
    sys.exit(1)
print('Public-content checks passed. Review images and use a secret scanner before publishing.')
