#!/usr/bin/env python3
"""Stamp versions and build existing app recipes without handling release secrets."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from store_release import slug


def run(*args, cwd=None):
    subprocess.run(args, check=True, cwd=cwd)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--version', default='')
    args = p.parse_args()
    config = json.loads(Path('store-app.json').read_text())
    recipe = config['build']['recipe']
    run_number = int(os.environ['GITHUB_RUN_NUMBER'])
    code = 1000000 + run_number
    if recipe == 'flickplayer':
        path = Path('app/build.gradle.kts')
        text = path.read_text()
        original = re.search(r'versionName\s*=\s*"([^"]+)"', text)[1]
        version = slug(args.version or original.split('+')[0] + '+build.' + str(run_number))
        text = re.sub(r'versionName\s*=\s*"[^"]+"', 'versionName = "' + version + '"', text)
        text = re.sub(r'versionCode\s*=\s*\d+', 'versionCode = ' + str(code), text)
        path.write_text(text)
    elif recipe == 'termux':
        path = Path('app/build.gradle')
        text = path.read_text()
        original = re.search(r'versionName\s+"([^"]+)"', text)[1]
        version = slug(args.version or original.split('+')[0] + '+build.' + str(run_number))
        text, count = re.subn(r'(versionCode\s+)\d+', lambda m: m[1] + str(code), text)
        if count != 1:
            raise ValueError('Expected one Termux versionCode declaration')
        path.write_text(text)
        os.environ.update(TERMUX_APP_VERSION_NAME=version, TERMUX_PACKAGE_VARIANT='apt-android-7',
                          TERMUX_APK_VERSION_TAG='v' + version + '-apt-android-7-github-debug')
    else:
        path = Path(config['build']['manifest'])
        tree = ET.parse(path)
        root = tree.getroot()
        ns = '{http://schemas.android.com/apk/res/android}'
        original = root.get(ns + 'versionName')
        original_code = int(root.get(ns + 'versionCode', '0'))
        code = max(code, original_code + run_number)
        version = slug(args.version or original.split('+')[0] + '+build.' + str(run_number))
        # Preserve the original XML namespaces/format rather than reserializing with ns0.
        text = path.read_text()
        text, n = re.subn(r'android:versionName="[^"]*"', 'android:versionName="' + version + '"', text)
        text, m = re.subn(r'android:versionCode="\d+"', 'android:versionCode="' + str(code) + '"', text)
        if n != 1 or m != 1:
            raise ValueError('Expected exactly one manifest versionName/versionCode')
        path.write_text(text)
    sdk = Path(os.environ.get('ANDROID_HOME', os.environ.get('ANDROID_SDK_ROOT', '')))
    sdk_link = Path.home() / 'android-sdk'
    if not sdk_link.exists():
        sdk_link.symlink_to(sdk, target_is_directory=True)
    bt = sdk / 'build-tools/35.0.0'
    os.environ['PATH'] = str(bt) + os.pathsep + os.environ['PATH']
    os.environ['ANDROID_SDK_ROOT'] = str(sdk)
    # Temporary compilation key only. The release APK is re-signed in a separate step.
    key = Path.home() / '.android/debug.keystore'
    key.parent.mkdir(exist_ok=True)
    if not key.exists():
        run('keytool', '-genkeypair', '-keystore', str(key), '-storepass', 'android', '-keypass', 'android',
            '-alias', 'androiddebugkey', '-keyalg', 'RSA', '-keysize', '2048', '-validity', '10000',
            '-dname', 'CN=Temporary CI build')
    if recipe == 'store':
        run('npm', 'ci', cwd='webui')
        run('npx', 'tsc', '--noEmit', cwd='webui')
        run('npm', 'run', 'build', cwd='webui')
        shutil.rmtree('assets/www', ignore_errors=True)
        shutil.copytree('webui/dist', 'assets/www')
        run('bash', 'build.sh')
        apk = 'build/app-store.apk'
    elif recipe in ('flickjp', 'sniffer'):
        run('bash', 'build.sh')
        apk = 'build/' + config['id'] + '.apk'
    elif recipe == 'kiwi':
        run('bash', 'scripts/bundle-serve-ci.sh')
        run('bash', 'app/build.sh')
        apk = 'app/build/kiwi-engine.apk'
    elif recipe == 'map':
        run('python3', 'resolve_deps.py')
        # Same bootstrap map as the existing development release recipe.
        directory = Path('src/main/assets/bootstrap')
        directory.mkdir(parents=True, exist_ok=True)
        run('gh', 'release', 'download', 'basemap-japan-v1', '--repo', os.environ['GITHUB_REPOSITORY'],
            '--pattern', 'japan.mbtiles', '--dir', str(directory), '--clobber')
        run('bash', 'build_tp.sh')
        apk = 'build/map-app.apk'
    elif recipe == 'flickplayer':
        run('gradle', 'assembleRelease', '--no-daemon')
        apk = 'app/build/outputs/apk/release/app-release-unsigned.apk'
    elif recipe == 'termux':
        run('bash', 'gradlew', 'assembleDebug', '--no-daemon')
        matches = list(Path('app/build/outputs/apk/debug').glob('*_universal.apk'))
        if len(matches) != 1:
            raise ValueError('Expected one universal Termux APK')
        apk = str(matches[0])
    else:
        raise ValueError('Unsupported build recipe: ' + recipe)
    if not Path(apk).is_file():
        raise ValueError('Build did not produce expected APK')
    with open(os.environ['GITHUB_OUTPUT'], 'a') as out:
        out.write('version=' + version + '\napk=' + apk + '\n')


if __name__ == '__main__':
    main()
