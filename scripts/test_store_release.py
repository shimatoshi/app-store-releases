import copy
import unittest
import argparse
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch
from store_release import upsert, validate, sync


class CatalogueTests(unittest.TestCase):
    def setUp(self):
        self.source = {'id': 'note', 'repository': 'shimatoshi/note', 'type': 'pwa',
                       'app': {'name': 'Note', 'url': 'https://note.example'}}
        self.meta = dict(schemaVersion=1, appId='note', sourceRepository='shimatoshi/note',
                         type='pwa', sourceCommit='a' * 40, versionName='2.0+build.1',
                         tagName='v2.0+build.1', date='2026-10-14T05:00:00Z', changelog='Update')

    def test_pwa_retry_and_old_event_do_not_duplicate_or_downgrade(self):
        manifest = {'apps': []}
        upsert(manifest, self.source, self.meta)
        upsert(manifest, self.source, self.meta)
        older = dict(self.meta, versionName='1.0', tagName='v1.0', date='2026-09-01T00:00:00Z')
        upsert(manifest, self.source, older)
        self.assertEqual(len(manifest['apps'][0]['versions']), 2)
        self.assertEqual(manifest['apps'][0]['latestVersion'], '2.0+build.1')

    def test_same_pwa_version_other_commit_rejected(self):
        manifest = {'apps': []}
        upsert(manifest, self.source, self.meta)
        with self.assertRaises(ValueError):
            upsert(manifest, self.source, dict(self.meta, sourceCommit='b' * 40))

    def apk(self):
        source = dict(self.source, type='apk')
        meta = dict(self.meta, type='apk', packageName='net.localhost.note', versionCode=1001,
                    assetName='note-v2.0+build.1.apk', size=123, sha256='1' * 64,
                    signingCertificateSha256='2' * 64)
        return source, meta

    def test_apk_preserves_editorial_and_legacy_history(self):
        source, meta = self.apk()
        manifest = {'apps': [{'id': 'note', 'type': 'apk', 'name': 'Custom name',
                             'screenshots': ['photo.png'], 'versions': [{'versionCode': 1}]}]}
        url = 'https://github.com/shimatoshi/note/releases/download/v2/note.apk'
        upsert(manifest, source, meta, url)
        upsert(manifest, source, meta, url)
        self.assertEqual(manifest['apps'][0]['name'], 'Custom name')
        self.assertEqual(manifest['apps'][0]['screenshots'], ['photo.png'])
        self.assertEqual(len(manifest['apps'][0]['versions']), 2)
        self.assertEqual(manifest['apps'][0]['versions'][0]['apkUrl'], url)

    def test_apk_changed_key_or_same_code_changed_bytes_rejected(self):
        source, meta = self.apk()
        manifest = {'apps': []}
        url = 'https://github.com/shimatoshi/note/releases/download/v2/note.apk'
        upsert(manifest, source, meta, url)
        for changed in ({'signingCertificateSha256': '3' * 64}, {'sha256': '4' * 64},
                        {'packageName': 'net.localhost.other'}):
            with self.assertRaises(ValueError):
                upsert(copy.deepcopy(manifest), source, dict(meta, **changed), url)

    def test_source_tag_and_direct_download_contract(self):
        with self.assertRaises(ValueError):
            validate(dict(self.meta, sourceRepository='someone/else'), self.source)
        with self.assertRaises(ValueError):
            validate(dict(self.meta, tagName='not-a-version'), self.source)
        source, meta = self.apk()
        with self.assertRaises(ValueError):
            upsert({'apps': []}, source, meta, 'https://github.com/shimatoshi/note/releases/tag/v2')

    def test_private_access_failure_does_not_block_valid_public_pwa(self):
        inaccessible = dict(self.source, id='private-app', repository='shimatoshi/private-app')
        release = {'tag_name': self.meta['tagName'], 'draft': False, 'prerelease': False,
                   'html_url': 'https://github.com/shimatoshi/note/releases/tag/' + self.meta['tagName'],
                   'assets': [{'name': 'store-release.json'}]}
        def fake_api(path, token=None):
            if 'private-app' in path:
                raise RuntimeError('Not Found (HTTP 404)')
            return [release] if '/releases?' in path else {'private': False}
        def fake_download(repo, tag, filename, directory, token=None):
            path = Path(directory) / filename
            path.write_text(json.dumps(self.meta))
            return path
        with tempfile.TemporaryDirectory() as tmp:
            source_path = Path(tmp) / 'sources.json'
            manifest_path = Path(tmp) / 'manifest.json'
            source_path.write_text(json.dumps({'sources': [inaccessible, self.source]}))
            manifest_path.write_text(json.dumps({'apps': []}))
            previous_cwd = os.getcwd()
            try:
                os.chdir(tmp)
                with patch('store_release.api', side_effect=fake_api), patch('store_release.download', side_effect=fake_download):
                    sync(argparse.Namespace(sources=str(source_path), manifest=str(manifest_path)))
                apps = json.loads(manifest_path.read_text())['apps']
                self.assertEqual([app['id'] for app in apps], ['note'])
                self.assertEqual(apps[0]['latestVersion'], self.meta['versionName'])
                self.assertEqual(len(json.loads(Path('sync-status.json').read_text())['errors']), 1)
            finally:
                os.chdir(previous_cwd)


if __name__ == '__main__':
    unittest.main()
