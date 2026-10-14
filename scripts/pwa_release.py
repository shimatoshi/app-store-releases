#!/usr/bin/env python3
"""Publish a PWA version only after a successful production deployment of this commit."""
import argparse
import json
import os
from pathlib import Path
import subprocess
from store_release import api, publish, slug

p = argparse.ArgumentParser()
p.add_argument('--deployment-id', required=True)
args = p.parse_args()
repo = os.environ['GITHUB_REPOSITORY']
deployment = api('repos/' + repo + '/deployments/' + str(int(args.deployment_id)))
if deployment.get('environment', '').lower() != 'production' or deployment.get('transient_environment'):
    raise SystemExit('Only successful production deployments may publish Store versions')
statuses = api('repos/' + repo + '/deployments/' + str(deployment['id']) + '/statuses')
if not statuses or statuses[0]['state'] != 'success':
    raise SystemExit('Production deployment is not currently successful')
commit = deployment['sha']
if subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip() != commit:
    raise SystemExit('Checkout must match the successfully deployed commit')
repo_info = api('repos/' + repo)
head = api('repos/' + repo + '/commits/' + repo_info['default_branch'])['sha']
if commit != head:
    raise SystemExit('Stale deployment event; refusing to advertise it as latest')
config = json.loads(Path('store-app.json').read_text())
package = Path(config.get('versionFile', 'package.json'))
base = json.loads(package.read_text()).get('version', '1.0.0') if package.exists() else '1.0.0'
version = slug(base.split('+')[0] + '+' + commit[:12])
publish(argparse.Namespace(config='store-app.json', commit=commit, version=version, apk=None))
