#!/usr/bin/env python3
"""Sync printer firmware configs against upstream Marlin/Configurations releases.

check  - for every printer in the manifest, look for a newer `release-*` branch
         in its config_repo, test-apply its patches against the new stock files,
         and either advance tracked_version + dispatch a build, or open an issue.
apply  - fetch the stock config for one printer/version and apply its patches
         into a destination directory (used by the build workflow).
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote

import requests
import yaml

MANIFEST_DEFAULT = "printers.yaml"
GITHUB_API = "https://api.github.com"


def gh_headers(token):
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def load_manifest(path):
    with open(path) as f:
        return yaml.safe_load(f)


def save_manifest(data, path):
    with open(path, "w") as f:
        yaml.safe_dump(data, f, sort_keys=False)


def parse_version(v):
    parts = [int(p) for p in re.findall(r"\d+", v)]
    parts += [0] * (4 - len(parts))
    return tuple(parts[:4])


def list_release_branches(repo, token):
    branches = []
    page = 1
    while True:
        resp = requests.get(
            f"{GITHUB_API}/repos/{repo}/branches",
            headers=gh_headers(token),
            params={"per_page": 100, "page": page},
            timeout=30,
        )
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        branches.extend(b["name"] for b in batch)
        if len(batch) < 100:
            break
        page += 1
    return branches


def latest_release_version(repo, token):
    candidates = []
    for name in list_release_branches(repo, token):
        m = re.fullmatch(r"release-([\d.]+)", name)
        if m:
            candidates.append((parse_version(m.group(1)), m.group(1)))
    if not candidates:
        raise RuntimeError(f"no release-* branches found in {repo}")
    return max(candidates, key=lambda c: c[0])


def raw_url(repo, ref, path):
    return f"https://raw.githubusercontent.com/{repo}/{quote(ref)}/{quote(path, safe='/')}"


def fetch_file(repo, ref, path, token):
    resp = requests.get(raw_url(repo, ref, path), timeout=30)
    resp.raise_for_status()
    return resp.content


def list_dir(repo, ref, path, token):
    resp = requests.get(
        f"{GITHUB_API}/repos/{repo}/contents/{quote(path, safe='/')}",
        headers=gh_headers(token),
        params={"ref": ref},
        timeout=30,
    )
    resp.raise_for_status()
    return [e for e in resp.json() if e["type"] == "file"]


def apply_patches(patch_dir, target_dir):
    patch_dir = Path(patch_dir)
    if not patch_dir.is_dir():
        return True, "no patches for this printer"
    log = []
    for patch_file in sorted(patch_dir.glob("*.patch")):
        result = subprocess.run(
            ["patch", "-p1", "--forward", "-i", str(patch_file.resolve())],
            cwd=target_dir,
            capture_output=True,
            text=True,
        )
        log.append(f"$ patch -p1 -i {patch_file.name}\n{result.stdout}{result.stderr}")
        if result.returncode != 0:
            return False, "\n".join(log)
    return True, "\n".join(log)


def try_patch_only(printer, version, token):
    """Fetch just the files that have patches and test-apply them (used by `check`)."""
    patch_dir = Path("patches") / printer["name"]
    patch_files = sorted(patch_dir.glob("*.patch")) if patch_dir.is_dir() else []
    with tempfile.TemporaryDirectory() as tmp:
        for pf in patch_files:
            filename = pf.name[: -len(".patch")]
            content = fetch_file(
                printer["config_repo"], f"release-{version}",
                f"{printer['config_path']}/{filename}", token,
            )
            (Path(tmp) / filename).write_bytes(content)
        return apply_patches(patch_dir, tmp)


def find_conflict_issue(repo_full, token, printer_name):
    resp = requests.get(
        f"{GITHUB_API}/repos/{repo_full}/issues",
        headers=gh_headers(token),
        params={"state": "open", "labels": "patch-conflict"},
        timeout=30,
    )
    resp.raise_for_status()
    prefix = f"Patch conflict: {printer_name} ->"
    return next((i for i in resp.json() if i["title"].startswith(prefix)), None)


def open_conflict_issue(repo_full, token, printer_name, version, log):
    if find_conflict_issue(repo_full, token, printer_name):
        print(f"  conflict issue already open for {printer_name}, skipping")
        return
    title = f"Patch conflict: {printer_name} -> {version}"
    body = (
        f"Automatic patch apply failed for `{printer_name}` against `release-{version}`.\n\n"
        f"Regenerate the patches in `patches/{printer_name}/` against the new stock config "
        f"and bump `tracked_version` for `{printer_name}` in `printers.yaml` once fixed.\n\n"
        f"```\n{log}\n```"
    )
    resp = requests.post(
        f"{GITHUB_API}/repos/{repo_full}/issues",
        headers=gh_headers(token),
        json={"title": title, "body": body, "labels": ["patch-conflict"]},
        timeout=30,
    )
    resp.raise_for_status()
    print(f"  opened issue: {resp.json()['html_url']}")


def dispatch_build(repo_full, token, printer_name, version):
    resp = requests.post(
        f"{GITHUB_API}/repos/{repo_full}/actions/workflows/build-firmware.yml/dispatches",
        headers=gh_headers(token),
        json={
            "ref": os.environ.get("GITHUB_REF_NAME", "main"),
            "inputs": {"printer": printer_name, "version": version},
        },
        timeout=30,
    )
    resp.raise_for_status()
    print(f"  dispatched build-firmware.yml for {printer_name} @ {version}")


def cmd_check(args):
    token = os.environ.get("GITHUB_TOKEN")
    repo_full = os.environ.get("GITHUB_REPOSITORY")
    manifest = load_manifest(args.manifest)
    changed = False
    for printer in manifest["printers"]:
        name = printer["name"]
        current = printer["tracked_version"]
        latest_tuple, latest_str = latest_release_version(printer["config_repo"], token)
        if latest_tuple <= parse_version(current):
            print(f"{name}: up to date ({current})")
            continue
        print(f"{name}: {current} -> {latest_str} available, testing patch apply...")
        ok, log = try_patch_only(printer, latest_str, token)
        if ok:
            print(f"{name}: patches apply cleanly")
            printer["tracked_version"] = latest_str
            changed = True
            if not args.dry_run:
                dispatch_build(repo_full, token, name, latest_str)
        else:
            print(f"{name}: patch conflict\n{log}")
            if not args.dry_run:
                open_conflict_issue(repo_full, token, name, latest_str, log)
    if changed:
        if args.dry_run:
            print(f"[dry-run] would update {args.manifest}")
        else:
            save_manifest(manifest, args.manifest)
            print(f"updated {args.manifest}")


def cmd_apply(args):
    token = os.environ.get("GITHUB_TOKEN")
    manifest = load_manifest(args.manifest)
    printer = next((p for p in manifest["printers"] if p["name"] == args.printer), None)
    if printer is None:
        sys.exit(f"unknown printer: {args.printer}")
    version = args.version or printer["tracked_version"]
    ref = f"release-{version}"
    dest = Path(args.dest)
    dest.mkdir(parents=True, exist_ok=True)
    for entry in list_dir(printer["config_repo"], ref, printer["config_path"], token):
        content = fetch_file(printer["config_repo"], ref, f"{printer['config_path']}/{entry['name']}", token)
        (dest / entry["name"]).write_bytes(content)
    ok, log = apply_patches(Path("patches") / printer["name"], dest)
    if not ok:
        sys.exit(f"patch apply failed for {printer['name']} @ {version}:\n{log}")
    print(f"applied {printer['name']} @ {version} into {dest}")


def cmd_resolve(args):
    manifest = load_manifest(args.manifest)
    printer = next((p for p in manifest["printers"] if p["name"] == args.printer), None)
    if printer is None:
        sys.exit(f"unknown printer: {args.printer}")
    version = args.version or printer["tracked_version"]
    fields = {"version": version, "board": printer["board"], "marlin_repo": printer["marlin_repo"]}
    gh_output = os.environ.get("GITHUB_OUTPUT")
    lines = "".join(f"{k}={v}\n" for k, v in fields.items())
    if gh_output:
        with open(gh_output, "a") as f:
            f.write(lines)
    else:
        print(lines, end="")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=MANIFEST_DEFAULT)
    sub = parser.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser("check", help="check upstream for new releases and test patches")
    p_check.add_argument("--dry-run", action="store_true")
    p_check.set_defaults(func=cmd_check)

    p_apply = sub.add_parser("apply", help="fetch stock config + apply patches for one printer")
    p_apply.add_argument("--printer", required=True)
    p_apply.add_argument("--version", default=None)
    p_apply.add_argument("--dest", required=True)
    p_apply.set_defaults(func=cmd_apply)

    p_resolve = sub.add_parser("resolve", help="print a printer's board/marlin_repo/version")
    p_resolve.add_argument("--printer", required=True)
    p_resolve.add_argument("--version", default=None)
    p_resolve.set_defaults(func=cmd_resolve)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
