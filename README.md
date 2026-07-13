# Marlin-Lazy-Build
Build Marlin firmware with GitHub Actions, and keep it building itself as upstream
releases new versions.

## How it works

Printers you build for are listed in [printers.yaml](printers.yaml). Each entry points
at a board environment, a stock config from [MarlinFirmware/Configurations](https://github.com/MarlinFirmware/Configurations)
(one of their `release-<version>` branches), and the Marlin version currently tracked.
Your customizations live as small unified diffs in `patches/<printer>/*.patch` — one
patch per changed file, applied on top of the stock config at build time. Files you
haven't customized are simply fetched fresh from upstream; nothing of upstream is
forked or vendored.

- **[check-updates.yml](.github/workflows/check-updates.yml)** runs daily (and on
  demand). For each printer it checks whether a newer `release-*` branch exists
  upstream and test-applies that printer's patches against it.
  - Clean apply → `tracked_version` is advanced and
    [build-firmware.yml](.github/workflows/build-firmware.yml) is dispatched
    automatically.
  - Conflict → a GitHub issue labeled `patch-conflict` is opened instead, so you only
    have to step in when there's an actual conflict to resolve.
- **[build-firmware.yml](.github/workflows/build-firmware.yml)** builds one printer:
  fetches Marlin at the resolved version, applies that printer's patches, compiles with
  PlatformIO, and publishes the `.bin` + its md5 as a GitHub release. Can also be
  dispatched manually to rebuild any printer/version on demand.

## Adding a printer

1. Add an entry to `printers.yaml`: `name`, `board` (PlatformIO environment), `marlin_repo`,
   `config_repo` (normally `MarlinFirmware/Configurations`), `config_path` (the example
   directory for your board), and `tracked_version` (the release you're starting from).
2. Customize the config: fetch the stock files from `config_repo` at
   `release-<tracked_version>`/`config_path`, edit a copy however you like, then for each
   changed file write a patch to `patches/<name>/<File>.patch`, e.g.:
   ```sh
   diff -u --label a/Configuration.h --label b/Configuration.h stock/Configuration.h mine/Configuration.h > patches/<name>/Configuration.h.patch
   ```
3. Commit. No workflow changes needed — `check-updates.yml` and `build-firmware.yml`
   both read the manifest.

## Resolving a patch conflict

When upstream changes a line your patch also touches, `check-updates.yml` opens an
issue instead of silently failing. To fix: pull the new stock file at the version named
in the issue, re-apply your intended change by hand, regenerate the patch (same `diff -u`
command as above), commit, and bump `tracked_version` for that printer in
`printers.yaml`.

## Manually building or rebuilding a version

Dispatch **build-firmware.yml** from the Actions tab with:

| Input          | Note                                                                 | Required |
|----------------|-----------------------------------------------------------------------|----------|
| printer        | Name from `printers.yaml`                                             | Y        |
| version        | Marlin version to build. Defaults to the printer's `tracked_version`  | N        |
| release_name   | Release name for compiled firmware. Defaults to `<printer>-<version>` | N        |
