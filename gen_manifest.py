#!/usr/bin/env python3
"""app-store-releases 用 manifest.json を生成/更新する。

APKの追加(バージョン履歴に追記):
  python3 gen_manifest.py apk <id> <apk_path> [--changelog "..."]

PWAエントリの追加/更新:
  python3 gen_manifest.py pwa <id> --name "名前" --url "https://..." --icon "🚉" --desc "説明"

既存の manifest.json があれば読み込んで追記する(なければ新規作成)。
apkUrl は https://github.com/shimatoshi/app-store-releases/releases/download/<id>-v<versionCode>/<id>.apk
"""
import argparse
import hashlib
import json
import re
import subprocess
import os
from datetime import datetime, timezone

MANIFEST_PATH = "manifest.json"

NAMES = {
    "map-app": "Map",
    "flickjp": "FlickJP",
    "kiwi-engine": "kiwi-engine",
    "app-store": "Store",
    "sniffer-browser": "Sniffer",
}
ICON_BASE = "https://raw.githubusercontent.com/shimatoshi/app-store-releases/main/icons/"
ICONS = {
    "map-app": ICON_BASE + "map-app.png",
    "flickjp": ICON_BASE + "flickjp.png",
    "kiwi-engine": ICON_BASE + "kiwi-engine.png",
    "app-store": ICON_BASE + "app-store.png",
    "sniffer-browser": ICON_BASE + "sniffer-browser.png",
}
DESCRIPTIONS = {
    "map-app": "OsmAnd代替のオフライン地図アプリ",
    "flickjp": "自作フリック日本語IME",
    "kiwi-engine": "自作ZIMオフライン書庫ビューワー",
    "app-store": "自作アプリの一覧・更新管理アプリ",
    "sniffer-browser": "広告ブロック・メディア検出ダウンロード機能付きWebViewブラウザ",
}
CATEGORIES = {
    "map-app": "地図・移動",
    "flickjp": "入力・システム",
    "kiwi-engine": "メディア",
    "app-store": "生産性",
    "sniffer-browser": "メディア",
}


def load_manifest():
    if os.path.exists(MANIFEST_PATH):
        with open(MANIFEST_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {"apps": []}


def save_manifest(manifest):
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


def badging(apk):
    out = subprocess.run(["aapt", "dump", "badging", apk], capture_output=True, text=True).stdout
    m = re.search(r"package: name='([^']+)' versionCode='(\d+)' versionName='([^']*)'", out)
    if not m:
        raise RuntimeError(f"badging parse failed for {apk}: {out[:200]}")
    return m.group(1), int(m.group(2)), m.group(3)


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def cmd_apk(args):
    manifest = load_manifest()
    package_name, version_code, version_name = badging(args.apk_path)
    size = os.path.getsize(args.apk_path)
    digest = sha256_of(args.apk_path)
    basename = f"{args.id}.apk"
    apk_url = (
        f"https://github.com/shimatoshi/app-store-releases/releases/download/"
        f"{args.id}-v{version_code}/{basename}"
    )
    version_entry = {
        "versionCode": version_code,
        "versionName": version_name,
        "apkUrl": apk_url,
        "size": size,
        "sha256": digest,
        "changelog": args.changelog or "",
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }

    entry = next((a for a in manifest["apps"] if a["id"] == args.id), None)
    if entry is None:
        entry = {
            "id": args.id,
            "type": "apk",
            "packageName": package_name,
            "name": NAMES.get(args.id, args.id),
            "icon": ICONS.get(args.id, "📦"),
            "description": DESCRIPTIONS.get(args.id, ""),
            "category": CATEGORIES.get(args.id, "その他"),
            "versions": [],
        }
        manifest["apps"].append(entry)

    entry["versions"] = [v for v in entry["versions"] if v["versionCode"] != version_code]
    entry["versions"].insert(0, version_entry)
    entry["versions"].sort(key=lambda v: v["versionCode"], reverse=True)

    save_manifest(manifest)


def cmd_pwa(args):
    manifest = load_manifest()
    entry = next((a for a in manifest["apps"] if a["id"] == args.id), None)
    if entry is None:
        entry = {"id": args.id, "type": "pwa"}
        manifest["apps"].append(entry)
    entry.update({
        "type": "pwa",
        "name": args.name,
        "icon": args.icon,
        "description": args.desc,
        "url": args.url,
        "category": args.category or entry.get("category") or CATEGORIES.get(args.id, "その他"),
    })
    save_manifest(manifest)


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    p_apk = sub.add_parser("apk")
    p_apk.add_argument("id")
    p_apk.add_argument("apk_path")
    p_apk.add_argument("--changelog", default="")
    p_apk.set_defaults(func=cmd_apk)

    p_pwa = sub.add_parser("pwa")
    p_pwa.add_argument("id")
    p_pwa.add_argument("--name", required=True)
    p_pwa.add_argument("--url", required=True)
    p_pwa.add_argument("--icon", default="🌐")
    p_pwa.add_argument("--desc", default="")
    p_pwa.add_argument("--category", default="")
    p_pwa.set_defaults(func=cmd_pwa)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
