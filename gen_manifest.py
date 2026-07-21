#!/usr/bin/env python3
"""app-store-releases 用 manifest.json を、カレントディレクトリのAPKから生成する。
使い方: python3 gen_manifest.py <id>:<apk_path> <id>:<apk_path> ...
各APKの package/versionCode/versionName は aapt dump badging から読む。
apkUrl は https://github.com/shimatoshi/app-store-releases/releases/download/<id>-v<versionCode>/<apk_basename>
"""
import hashlib
import json
import re
import subprocess
import sys
import os

NAMES = {
    "map-app": "Map",
    "flickjp": "FlickJP",
    "kiwi-engine": "kiwi-engine",
    "app-store": "Store",
}

CHANGELOG = {
    "map-app": "OsmAnd代替のオフライン地図アプリ",
    "flickjp": "自作フリック日本語IME",
    "kiwi-engine": "自作ZIMオフライン書庫ビューワー",
    "app-store": "自作アプリの一覧・更新管理アプリ",
}


def badging(apk):
    out = subprocess.run(["aapt", "dump", "badging", apk], capture_output=True, text=True).stdout
    pkg = re.search(r"package: name='([^']+)' versionCode='(\d+)' versionName='([^']*)'", out)
    if not pkg:
        raise RuntimeError(f"badging parse failed for {apk}: {out[:200]}")
    return pkg.group(1), int(pkg.group(2)), pkg.group(3)


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    apps = []
    for arg in sys.argv[1:]:
        app_id, apk_path = arg.split(":", 1)
        package_name, version_code, version_name = badging(apk_path)
        size = os.path.getsize(apk_path)
        digest = sha256_of(apk_path)
        basename = f"{app_id}.apk"
        apk_url = (
            f"https://github.com/shimatoshi/app-store-releases/releases/download/"
            f"{app_id}-v{version_code}/{basename}"
        )
        apps.append({
            "id": app_id,
            "packageName": package_name,
            "name": NAMES.get(app_id, app_id),
            "versionCode": version_code,
            "versionName": version_name,
            "apkUrl": apk_url,
            "size": size,
            "sha256": digest,
            "changelog": CHANGELOG.get(app_id, ""),
        })

    manifest = {"apps": apps}
    with open("manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
