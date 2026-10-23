#!/usr/bin/env python3
# Copyright 2018-2026 the Deno authors. MIT license.
"""Compute complete, validated identities for the native build caches."""

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REQUIRED_ENV = (
    "RUNNER_OS", "RUNNER_ARCH", "ImageOS", "ImageVersion", "GITHUB_SHA",
    "CARGO_PROFILE_RELEASE_LTO", "CARGO_PROFILE_RELEASE_CODEGEN_UNITS",
    "RUSTC_WRAPPER",
)
TOOLS = {
    "rustc": ["rustc", "-vV"],
    "cc": ["cc", "--version"],
    "linker": ["ld.lld", "--version"],
    "sccache": ["sccache", "--version"],
}
RECIPE_FILES = (
    "Cargo.lock", "rust-toolchain.toml", ".cargo/config.toml",
    "tools/upstream_v8/sources.json", "tools/upstream_v8/prepare.py",
    "tools/upstream_v8/deps.py", "tools/upstream_v8/cache.py",
)
OVERRIDES = (
    "RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS", "GN_ARGS", "CC", "CXX",
    "CLANG_BASE_PATH", "CXXSTDLIB", "V8_FORCE_DEBUG",
)


def require_value(name, value):
    if not isinstance(value, str) or not value.strip() or set(value.strip()) == {"0"}:
        raise ValueError(f"Missing or zero cache input: {name}")
    return value


def cache_keys(root, environment, versions, cargo_manifests):
    inputs = {name: require_value(name, environment.get(name)) for name in REQUIRED_ENV}
    revision = inputs.pop("GITHUB_SHA")
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Cache revision must be a full commit SHA")
    if (inputs["RUNNER_OS"], inputs["RUNNER_ARCH"]) != ("Linux", "X64"):
        raise ValueError("The native cache only supports Linux X64")
    inputs["tools"] = {name: require_value(name, versions.get(name)) for name in TOOLS}
    inputs["overrides"] = {
        name: require_value(name, environment[name]) for name in OVERRIDES if name in environment
    }
    if not cargo_manifests or "Cargo.toml" not in cargo_manifests:
        raise ValueError("Cargo manifest list is incomplete")
    paths = set(RECIPE_FILES) | set(cargo_manifests)
    for component in ("build", "v8", "rusty_v8", "bindgen"):
        patches = sorted((root / "tools/upstream_v8/patches" / component).glob("*.patch"))
        if not patches:
            raise ValueError(f"Missing patches for {component}")
        paths.update(str(path.relative_to(root)) for path in patches)
    inputs["files"] = {}
    for path in sorted(paths):
        relative = Path(path)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"Cache input escapes repository: {path}")
        content = (root / relative).read_bytes()
        if not content.strip():
            raise ValueError(f"Empty cache input file: {path}")
        inputs["files"][path] = hashlib.sha256(content).hexdigest()
    digest = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
    # Restore only within the same complete build configuration. The commit
    # suffix lets later builds save updated outputs without replacing a cache.
    prefix = f"upstream-v8-v1-linux-x64-{digest}-"
    return {
        f"{kind}_{field}": f"{kind}-{prefix}" + (revision if field == "key" else "")
        for kind in ("sccache", "cargo") for field in ("key", "prefix")
    }


def main():
    versions = {name: subprocess.check_output(command, text=True).strip()
                for name, command in TOOLS.items()}
    manifests = subprocess.check_output(
        ["git", "ls-files", "-z", "--", "Cargo.toml", "**/Cargo.toml"], cwd=ROOT,
    ).decode().rstrip("\0").split("\0")
    keys = cache_keys(ROOT, os.environ, versions, manifests)
    output = Path(require_value("GITHUB_OUTPUT", os.environ.get("GITHUB_OUTPUT")))
    with output.open("a") as file:
        for name, value in keys.items():
            file.write(f"{name}={value}\n")
            print(f"{name}={value}")


if __name__ == "__main__":
    main()
