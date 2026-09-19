#!/usr/bin/env python3
"""Initialize the first account against a local or explicitly selected deployment."""
import argparse
import getpass
import json
import urllib.error
import urllib.request

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--url', default='http://localhost:8080')
args = parser.parse_args()
email = input('Administrator email: ').strip()
password = getpass.getpass('Password (at least 12 characters): ')
if len(password) < 12:
    raise SystemExit('Use a password with at least 12 characters.')
if password != getpass.getpass('Repeat password: '):
    raise SystemExit('Passwords do not match.')
request = urllib.request.Request(
    args.url.rstrip('/') + '/api/v1/auth/bootstrap',
    data=json.dumps({'email': email, 'password': password}).encode(),
    headers={'Content-Type': 'application/json'}, method='POST',
)
try:
    with urllib.request.urlopen(request, timeout=30) as response:
        print('Administrator created. Open /login to sign in.')
except urllib.error.HTTPError as error:
    raise SystemExit(f'Bootstrap failed (HTTP {error.code}). Check whether initialization is already complete.')
