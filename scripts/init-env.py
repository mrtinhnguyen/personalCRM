#!/usr/bin/env python3
"""Create local Compose settings; never overwrite an existing .env."""
from pathlib import Path
import secrets

root = Path(__file__).resolve().parents[1]
settings = (root / '.env.example').read_text()
for key in ('POSTGRES_PASSWORD', 'SESSION_SECRET', 'IMPORT_HMAC_SECRET'):
    settings = settings.replace(f'{key}=replace-me', f'{key}={secrets.token_hex(32)}')
try:
    with (root / '.env').open('x') as output:
        (root / '.env').chmod(0o600)
        output.write(settings)
except FileExistsError:
    raise SystemExit('.env already exists; it was not changed.')
print('Created private .env with generated secrets. Default access: localhost only.')
