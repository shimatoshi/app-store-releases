#!/usr/bin/env python3
"""Re-sign only with the owner's persistent existing key; never generate a release key."""
import base64
import os
from pathlib import Path
import subprocess
import sys

key_data = os.environ.get('STORE_SIGNING_KEYSTORE_BASE64')
if not key_data:
    raise SystemExit('Missing STORE_SIGNING_KEYSTORE_BASE64: configure the EXISTING signing key in repository Actions secrets.')
key = Path(os.environ['RUNNER_TEMP']) / 'store-release.keystore'
try:
    key.write_bytes(base64.b64decode(''.join(key_data.split()), validate=True))
    key.chmod(0o600)
    bt = Path(os.environ['ANDROID_HOME']) / 'build-tools/35.0.0'
    env = os.environ.copy()
    env['STORE_KEYSTORE_PASSWORD'] = env.get('STORE_KEYSTORE_PASSWORD') or 'android'
    env['STORE_KEY_PASSWORD'] = env.get('STORE_KEY_PASSWORD') or env['STORE_KEYSTORE_PASSWORD']
    out = Path('store-signed.apk')
    subprocess.run([str(bt / 'apksigner'), 'sign', '--ks', str(key),
                    '--ks-pass', 'env:STORE_KEYSTORE_PASSWORD', '--key-pass', 'env:STORE_KEY_PASSWORD',
                    '--ks-key-alias', env.get('STORE_KEY_ALIAS') or 'androiddebugkey',
                    '--out', str(out), sys.argv[1]], check=True, env=env)
    subprocess.run([str(bt / 'apksigner'), 'verify', str(out)], check=True)
finally:
    key.unlink(missing_ok=True)
