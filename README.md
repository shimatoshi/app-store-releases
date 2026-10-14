# Store release automation

Android apps build and publish an immutable `v<versionName>` Release containing a versioned APK and `store-release.json`. PWA apps publish version metadata only after a successful production deployment of the exact source commit. The Store catalogue is synchronized by CI every 15 minutes, on `workflow_dispatch`, or on a `store-release` repository dispatch. GitHub scheduled jobs can run late.

## One-time setup

1. In **app-store-releases → Settings → Secrets and variables → Actions**, set `STORE_SOURCE_TOKEN`: a fine-grained GitHub token with **Contents: read** on the source repositories in `sources.json`. It is required to read private app repositories. The central workflow uses its own `GITHUB_TOKEN` for the public catalogue and distribution Releases; no cross-repository write token is needed.
2. In each Android source repository, set `STORE_SIGNING_KEYSTORE_BASE64` to the base64 encoding of its **existing signing keystore**. Do not generate a replacement key. Optionally set `STORE_KEYSTORE_PASSWORD`, `STORE_KEY_PASSWORD`, and `STORE_KEY_ALIAS`; defaults are `android`, the keystore password, and `androiddebugkey`. Secrets are consumed only in the signing step, and the temporary keystore is deleted afterwards.
3. PWA source repositories must emit GitHub `deployment_status` events for successful `Production` deployments (for example through their Vercel Git integration). Manually deployed sites must report a production deployment through GitHub's Deployments API; a plain push does not imply a successful deployment. The manual workflow input accepts an existing successful production `deployment_id` and verifies its SHA and state.

Never paste tokens or keystores into issues, source files, or chat. Configure them directly in GitHub Actions secrets. The GitHub connector used to install this automation cannot configure Actions secrets.

## Behavior

- `store-app.json` in each app describes its ID and build recipe. `sources.json` is the explicit source allowlist; data-only repositories and unfinished projects are not silently treated as released apps.
- Automatic Android versions use the current base version plus `+build.<workflow run number>`. Android versionCode is at least `1000000 + run number` and greater than the source manifest versionCode. A manually supplied version becomes both APK versionName and Release tag (`v` prefixed).
- PWA versions use the package version (or `1.0.0` for static sites) plus the deployed commit's first twelve hex digits. This changes on every deployed commit even when package.json was not manually bumped.
- Private source APKs are verified and mirrored into public `app-store-releases` Releases named `<appId>-v<version>`, so Android downloads do not need GitHub login. Public source APKs link directly to their own Release assets. Source code is not copied to the public distribution repository.
- Catalogue registration happens only after asset upload and signature/checksum validation. New signing certificates must match existing published APKs, including the legacy catalogue's first migration.
- Published versions are immutable. Retries preserve the original binary; catalogue entries are deduplicated. Old release events do not downgrade the latest version. Synchronization is atomic per app: a failed app retains its previous catalogue entry while other successfully verified apps still update. The CI reports failed sources in its job summary and remains failed until access or validation is repaired. A later run resumes safely.
- PWA notifications appear inside Store while it is open or when it is reopened/refreshed. They compare against the last acknowledged version, not the installed service-worker cache. First catalogue load establishes a baseline. Opening the PWA acknowledges its listed version. Background OS push notifications are not implemented.

## Usage

- Android: a push to the default branch triggers **Store APK release**, or use its manual **version** input. The fixed owner signing key is mandatory for release.
- PWA: production deployment success triggers **Store PWA version**. Development/preview/failed/stale deployments do not get advertised.
- Sync: run **Synchronize Store catalogue** to reflect new Releases immediately, or wait for the scheduled run.
- Existing legacy catalogue entries are retained until their new pipeline publishes a verified version. Newly registered APK apps show `公開準備中` until a release exists.

The existing independent debug/build workflows remain available. Their debug artifacts are not automatically advertised as installable updates.

## Verification

`python3 -m unittest discover -s scripts -p 'test_*.py' -v` validates idempotency, immutable versions, ordering, source validation, direct APK asset URLs, and signing-key changes. Store's source workflow also runs TypeScript checking and the Vite production build.
