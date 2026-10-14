#!/usr/bin/env python3
"""Release metadata contract and idempotent Store catalogue updates (stdlib only)."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import urllib.parse


def gh(*args, token=None, data=None):
    env = os.environ.copy()
    if token:
        env['GH_TOKEN'] = token
    p = subprocess.run(['gh', *args], input=data, capture_output=True, text=True, env=env)
    if p.returncode:
        raise RuntimeError(p.stderr.strip() or 'GitHub command failed')
    return p.stdout


def api(path, token=None):
    return json.loads(gh('api', path, token=token))


def slug(value):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.+-]*', value):
        raise ValueError('Invalid app ID or version')
    return value


def validate(meta, source):
    if meta.get('schemaVersion') != 1 or meta.get('appId') != source['id']:
        raise ValueError('Release does not match registered app')
    if meta.get('sourceRepository') != source['repository'] or meta.get('type') != source['type']:
        raise ValueError('Release source/type mismatch')
    slug(meta['versionName'])
    if meta.get('tagName') != 'v' + meta['versionName']:
        raise ValueError('Release tag must match versionName')
    if not re.fullmatch(r'[0-9a-f]{40}', meta.get('sourceCommit', '')):
        raise ValueError('Missing source commit')
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z', meta.get('date', '')):
        raise ValueError('Invalid release date')
    if meta['type'] == 'apk':
        if not isinstance(meta.get('versionCode'), int) or not 0 < meta['versionCode'] < 2100000000:
            raise ValueError('Invalid Android versionCode')
        if not re.fullmatch(r'[a-zA-Z][\w]*(?:\.[a-zA-Z][\w]*)+', meta.get('packageName', '')):
            raise ValueError('Invalid Android package')
        if meta.get('assetName') != source['id'] + '-v' + meta['versionName'] + '.apk':
            raise ValueError('Unexpected APK filename')
        for field in ('sha256', 'signingCertificateSha256'):
            if not re.fullmatch(r'[0-9a-f]{64}', meta.get(field, '')):
                raise ValueError('Missing APK digest or signing certificate')
        if not isinstance(meta.get('size'), int) or meta['size'] <= 0:
            raise ValueError('Invalid APK size')
    return meta


def upsert(manifest, source, meta, apk_url=None, release_url=None):
    """Preserve editorial content and legacy versions; reject key changes/downgrades."""
    validate(meta, source)
    apps = manifest.setdefault('apps', [])
    app = next((a for a in apps if a['id'] == source['id']), None)
    if app is None:
        app = dict(source['app'], id=source['id'], type=source['type'])
        apps.append(app)
    if app['type'] != source['type']:
        raise ValueError('Cannot change app type')
    version = {k: meta[k] for k in ('versionName', 'date', 'sourceCommit', 'changelog')}
    version['releaseUrl'] = release_url
    versions = app.setdefault('versions', [])
    if meta['type'] == 'apk':
        if app.get('packageName') and app['packageName'] != meta['packageName']:
            raise ValueError('Package changed; use a separate Store entry')
        for old in versions:
            cert = old.get('signingCertificateSha256')
            if cert and cert != meta['signingCertificateSha256']:
                raise ValueError('Signing key changed; refusing incompatible APK')
        existing = next((v for v in versions if v['versionCode'] == meta['versionCode']), None)
        if existing and existing.get('sha256') != meta['sha256']:
            raise ValueError('Immutable Android versionCode already has different APK')
        if not apk_url or not apk_url.startswith('https://github.com/') or '/releases/download/' not in apk_url:
            raise ValueError('APK must link directly to a GitHub release asset')
        app['packageName'] = meta['packageName']
        version.update({k: meta[k] for k in ('versionCode', 'size', 'sha256', 'signingCertificateSha256')})
        version['apkUrl'] = apk_url
        versions[:] = [v for v in versions if v['versionCode'] != meta['versionCode']] + [version]
        versions.sort(key=lambda v: v['versionCode'], reverse=True)
    else:
        existing = next((v for v in versions if v['versionName'] == meta['versionName']), None)
        if existing and existing.get('sourceCommit') != meta['sourceCommit']:
            raise ValueError('Immutable PWA version already belongs to another commit')
        app['url'] = source['app']['url']
        versions[:] = [v for v in versions if v['versionName'] != meta['versionName']] + [version]
        versions.sort(key=lambda v: (v['date'], v['versionName']), reverse=True)
    app['sourceRepository'] = source['repository']
    app['latestVersion'] = versions[0]['versionName']
    app['updatedAt'] = versions[0]['date']
    return manifest


def download(repo, tag, filename, directory, token=None):
    Path(directory).mkdir(parents=True, exist_ok=True)
    gh('release', 'download', tag, '--repo', repo, '--pattern', filename,
       '--dir', str(directory), '--clobber', token=token)
    return Path(directory) / filename


def signing_certificate(apk):
    output = subprocess.check_output(['apksigner', 'verify', '--print-certs', str(apk)], text=True)
    match = re.search(r'Signer #1 certificate SHA-256 digest: ([0-9a-fA-F]{64})', output)
    if not match:
        raise ValueError('Cannot verify APK signer')
    return match[1].lower()


def publish(args):
    config = json.loads(Path(args.config).read_text())
    repo = os.environ['GITHUB_REPOSITORY']
    commit = args.commit or os.environ['GITHUB_SHA']
    tag = 'v' + slug(args.version)
    source = {'id': config['id'], 'repository': repo, 'type': config['type'], 'app': config['app']}
    git_date = subprocess.check_output(['git', 'show', '-s', '--format=%cI', commit], text=True).strip()
    from datetime import datetime, timezone
    date = datetime.fromisoformat(git_date).astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    subject = subprocess.check_output(['git', 'show', '-s', '--format=%s', commit], text=True).strip()
    meta = dict(schemaVersion=1, appId=config['id'], type=config['type'], sourceRepository=repo,
                sourceCommit=commit, versionName=args.version, tagName=tag, date=date, changelog=subject)
    out = Path('store-publish')
    out.mkdir(exist_ok=True)
    assets = []
    if config['type'] == 'apk':
        apk = Path(args.apk)
        badging = subprocess.check_output(['aapt', 'dump', 'badging', str(apk)], text=True)
        match = re.search(r"package: name='([^']+)' versionCode='(\d+)' versionName='([^']*)'", badging)
        if not match or match[3] != args.version:
            raise ValueError('APK versionName does not match release version')
        cert = subprocess.check_output(['apksigner', 'verify', '--print-certs', str(apk)], text=True)
        digest = re.search(r'Signer #1 certificate SHA-256 digest: ([0-9a-fA-F]{64})', cert)
        if not digest:
            raise ValueError('Cannot verify APK signature')
        meta.update(packageName=match[1], versionCode=int(match[2]),
                    signingCertificateSha256=digest[1].lower(),
                    sha256=hashlib.sha256(apk.read_bytes()).hexdigest(), size=apk.stat().st_size,
                    assetName=config['id'] + '-' + tag + '.apk')
        import shutil
        dest = out / meta['assetName']
        shutil.copyfile(apk, dest)
        assets.append(str(dest))
    validate(meta, source)
    metadata = out / 'store-release.json'
    metadata.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + '\n')
    assets.append(str(metadata))
    releases = api(f'repos/{repo}/releases?per_page=100')
    existing = next((r for r in releases if r['tag_name'] == tag), None)
    if existing and not existing['draft']:
        with tempfile.TemporaryDirectory() as tmp:
            old = json.loads(download(repo, tag, 'store-release.json', tmp).read_text())
        if old.get('sourceCommit') != commit or old.get('versionName') != args.version:
            raise ValueError('Published tag is immutable and points to another commit')
        validate(old, source)
        if config['type'] == 'apk' and old['signingCertificateSha256'] != meta['signingCertificateSha256']:
            raise ValueError('Signing key changed during retry')
        print('Already published; preserving original release assets')
        return
    if not existing:
        gh('release', 'create', tag, '--repo', repo, '--target', commit, '--draft',
           '--title', config['app']['name'] + ' ' + tag, '--notes', subject)
    gh('release', 'upload', tag, *assets, '--repo', repo, '--clobber')
    gh('release', 'edit', tag, '--repo', repo, '--draft=false')
    print('Published ' + repo + ' ' + tag)


def sync(args):
    sources = json.loads(Path(args.sources).read_text())['sources']
    manifest_path = Path(args.manifest)
    manifest = json.loads(manifest_path.read_text())
    source_token = os.environ.get('STORE_SOURCE_TOKEN')
    target_token = os.environ.get('GH_TOKEN')
    target = os.environ.get('GITHUB_REPOSITORY', 'shimatoshi/app-store-releases')
    errors = []
    for source in sources:
        repo = source['repository']
        try:
            repo_info = api('repos/' + repo, token=source_token or target_token)
            releases = api('repos/' + repo + '/releases?per_page=30', token=source_token or target_token)
            for release in reversed(releases):
                if release['draft'] or release['prerelease']:
                    continue
                names = {a['name'] for a in release['assets']}
                if 'store-release.json' not in names:
                    continue
                with tempfile.TemporaryDirectory() as tmp:
                    meta = json.loads(download(repo, release['tag_name'], 'store-release.json', tmp,
                                               token=source_token or target_token).read_text())
                    validate(meta, source)
                    if meta['tagName'] != release['tag_name']:
                        raise ValueError('Asset metadata does not match release tag')
                    app = next((a for a in manifest['apps'] if a['id'] == source['id']), None)
                    old_versions = app.get('versions', []) if app else []
                    registered = next((v for v in old_versions if v.get('sourceCommit') == meta['sourceCommit']
                                       and v['versionName'] == meta['versionName']), None)
                    if registered:
                        if source['type'] == 'apk' and registered['sha256'] != meta['sha256']:
                            raise ValueError('Published APK changed after catalogue registration')
                        continue
                    apk_url = None
                    release_url = release['html_url']
                    if source['type'] == 'apk':
                        if meta['assetName'] not in names:
                            raise ValueError('APK asset missing from release')
                        # Even public assets are verified before being advertised.
                        apk = download(repo, release['tag_name'], meta['assetName'], tmp,
                                       token=source_token or target_token)
                        if hashlib.sha256(apk.read_bytes()).hexdigest() != meta['sha256'] or apk.stat().st_size != meta['size']:
                            raise ValueError('APK asset checksum/size mismatch')
                        if signing_certificate(apk) != meta['signingCertificateSha256']:
                            raise ValueError('APK signer does not match metadata')
                        # Pin the installed legacy distribution key on first migration too.
                        legacy = next((v for v in old_versions if v.get('apkUrl')), None)
                        if legacy and not legacy.get('signingCertificateSha256'):
                            parsed = urllib.parse.urlparse(legacy['apkUrl'])
                            parts = parsed.path.split('/')
                            if parsed.netloc != 'github.com' or len(parts) != 7 or parts[3:5] != ['releases', 'download']:
                                raise ValueError('Cannot verify legacy APK signing key')
                            legacy_apk = download('/'.join(parts[1:3]), urllib.parse.unquote(parts[5]),
                                                  urllib.parse.unquote(parts[6]), Path(tmp) / 'legacy',
                                                  token=target_token)
                            if signing_certificate(legacy_apk) != meta['signingCertificateSha256']:
                                raise ValueError('New APK is not signed with the legacy distribution key')
                            legacy['signingCertificateSha256'] = meta['signingCertificateSha256']
                        if repo_info['private']:
                            # Private Release URLs cannot be downloaded anonymously by Android.
                            public_tag = source['id'] + '-' + meta['tagName']
                            target_releases = api('repos/' + target + '/releases?per_page=100', token=target_token)
                            current = next((r for r in target_releases if r['tag_name'] == public_tag), None)
                            if current and not current['draft']:
                                old = json.loads(download(target, public_tag, 'store-release.json',
                                                          Path(tmp) / 'existing', token=target_token).read_text())
                                if old['sha256'] != meta['sha256']:
                                    raise ValueError('Public release is immutable')
                            else:
                                if not current:
                                    gh('release', 'create', public_tag, '--repo', target, '--draft',
                                       '--title', source['app']['name'] + ' ' + meta['tagName'],
                                       '--notes', meta['changelog'], token=target_token)
                                gh('release', 'upload', public_tag, str(apk), str(Path(tmp) / 'store-release.json'),
                                   '--repo', target, '--clobber', token=target_token)
                                gh('release', 'edit', public_tag, '--repo', target, '--draft=false', token=target_token)
                            release_url = 'https://github.com/' + target + '/releases/tag/' + urllib.parse.quote(public_tag, safe='')
                            apk_url = 'https://github.com/' + target + '/releases/download/' + urllib.parse.quote(public_tag, safe='') + '/' + urllib.parse.quote(meta['assetName'], safe='')
                        else:
                            apk_url = next(a['browser_download_url'] for a in release['assets'] if a['name'] == meta['assetName'])
                    upsert(manifest, source, meta, apk_url, release_url)
            print('Synced ' + repo)
        except (RuntimeError, ValueError, KeyError) as exc:
            errors.append(repo + ': ' + str(exc))
    if errors:
        # No partial catalogue commit: rerunning safely resumes any draft/published assets.
        raise RuntimeError('\n'.join(errors))
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('publish')
    p.add_argument('--config', default='store-app.json')
    p.add_argument('--version', required=True)
    p.add_argument('--apk')
    p.add_argument('--commit')
    p.set_defaults(func=publish)
    p = sub.add_parser('sync')
    p.add_argument('--sources', default='sources.json')
    p.add_argument('--manifest', default='manifest.json')
    p.set_defaults(func=sync)
    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
