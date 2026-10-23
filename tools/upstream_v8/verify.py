#!/usr/bin/env python3
# Copyright 2018-2026 the Deno authors. MIT license.
"""Verify and package the built Linux x64 Deno executable."""

import hashlib
import json
import platform
import shutil
import subprocess
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent


def main():
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise SystemExit("This packaging target is Linux x86_64")
    binary = ROOT / "target/release/deno"
    version = subprocess.check_output([binary, "--version"], text=True)
    manifest = json.loads((HERE / "sources.json").read_text())
    if "v8 " + manifest["v8_version"] not in version.splitlines()[1]:
        raise SystemExit(f"Unexpected runtime version: {version}")
    flags = ["--no-prompt", "--no-check", "--no-lock", "--cached-only", "--node-modules-dir=none"]
    flags += ["--deny-" + permission for permission in ["read", "write", "net", "env", "run", "sys", "ffi"]]
    flags += ["--v8-flags=--max-heap-size=27,--single-threaded,--single-threaded-gc,--disallow-code-generation-from-strings,--jitless"]
    subprocess.run([binary, "run", *flags, HERE / "smoke.js"], check=True, timeout=30)
    output = ROOT / "target/upstream-v8/package"
    output.mkdir(parents=True, exist_ok=True)
    name = "deno-x86_64-unknown-linux-gnu.zip"
    with zipfile.ZipFile(output / name, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.write(binary, "deno")
    checksum = hashlib.sha256((output / name).read_bytes()).hexdigest()
    (output / (name + ".sha256sum")).write_text(checksum + "  " + name + "\n")
    provenance = json.loads((ROOT / "target/upstream-v8/provenance.json").read_text())
    provenance["deno_commit"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    provenance["binary_sha256"] = hashlib.sha256(binary.read_bytes()).hexdigest()
    provenance["runtime_version"] = version
    provenance["validation"] = "VM-context CVE-2026-11645 regression and Synthetics permission/V8 flags"
    (output / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    shutil.copyfile(ROOT / "LICENSE.md", output / "LICENSE.md")
    print(version, end="")
    print(f"Package: {output / name}")


if __name__ == "__main__":
    main()
