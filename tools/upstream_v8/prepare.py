#!/usr/bin/env python3
# Copyright 2018-2026 the Deno authors. MIT license.
"""Materialize the pinned V8 source tree used by this Deno branch."""

import argparse
import hashlib
import json
import platform
import re
import subprocess
import tarfile
import tempfile
import urllib.request
from pathlib import Path, PurePosixPath

from deps import read_deps

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
SOURCES = ROOT / "target" / "upstream-v8" / "rusty_v8"


def run(*args, cwd=None, capture=False):
    print("+", " ".join(str(arg) for arg in args), flush=True)
    return subprocess.run(
        [str(arg) for arg in args], cwd=cwd, check=True, text=True,
        stdout=subprocess.PIPE if capture else None,
    ).stdout


def validate_source(source):
    revision = source.get("revision", "")
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision) or revision == "0" * 40:
        raise ValueError(f"Expected a nonzero, immutable commit: {revision!r}")
    repository = source.get("repository", "")
    if not isinstance(repository, str) or not repository.startswith(("https://github.com/", "https://chromium.googlesource.com/")):
        raise ValueError(f"Unexpected source repository: {repository!r}")
    if "path" in source:
        if not isinstance(source["path"], str):
            raise ValueError("Dependency path must be a string")
        path = PurePosixPath(source["path"])
        if not path.parts or path.is_absolute() or ".." in path.parts:
            raise ValueError(f"Invalid dependency path: {source['path']!r}")


def checkout(source, destination):
    validate_source(source)
    destination.mkdir(parents=True, exist_ok=True)
    if not (destination / ".git").exists():
        run("git", "init", "--quiet", destination)
        run("git", "remote", "add", "origin", source["repository"], cwd=destination)
    origin = run("git", "config", "--get", "remote.origin.url", cwd=destination, capture=True).strip()
    if origin != source["repository"]:
        raise ValueError(f"Unexpected origin in {destination}: {origin}")
    exists = subprocess.run(
        ["git", "cat-file", "-e", source["revision"] + "^{commit}"],
        cwd=destination, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ).returncode == 0
    if not exists:
        run("git", "fetch", "--depth=1", "origin", source["revision"], cwd=destination)
    run("git", "checkout", "--detach", source["revision"], cwd=destination)
    actual = run("git", "rev-parse", "HEAD", cwd=destination, capture=True).strip()
    if actual != source["revision"]:
        raise ValueError(f"Revision mismatch in {destination}")


def apply_patch(directory, patch):
    reverse = subprocess.run(
        ["git", "apply", "--reverse", "--check", str(patch)], cwd=directory,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    if reverse.returncode != 0:
        run("git", "apply", "--check", patch, cwd=directory)
        run("git", "apply", patch, cwd=directory)


def download_toolchain(dependency, directory):
    """Install the Linux x64 toolchain artifact with the checksum in V8 DEPS."""
    artifact = next(item for item in dependency["objects"]
                    if item["condition"] == 'host_os == "linux"')
    checksum = artifact["sha256sum"]
    if not re.fullmatch(r"[0-9a-f]{64}", checksum) or checksum == "0" * 64:
        raise ValueError("Toolchain checksum must be nonzero SHA-256")
    url = "https://storage.googleapis.com/" + dependency["bucket"] + "/" + artifact["object_name"]
    marker = directory / ".datadog-sha256"
    if marker.exists() and marker.read_text() == checksum:
        return url
    with tempfile.TemporaryFile() as archive:
        digest = hashlib.sha256()
        with urllib.request.urlopen(url, timeout=120) as response:
            while chunk := response.read(1024 * 1024):
                digest.update(chunk)
                archive.write(chunk)
        if digest.hexdigest() != checksum:
            raise ValueError(f"Toolchain checksum mismatch: {url}")
        archive.seek(0)
        directory.mkdir(parents=True, exist_ok=True)
        with tarfile.open(fileobj=archive, mode="r:xz") as bundle:
            bundle.extractall(directory, filter="data")
    marker.write_text(checksum)
    return url


def prepare(bindings_only=False, toolchains=False):
    if toolchains and (platform.system() != "Linux" or platform.machine() != "x86_64"):
        raise ValueError("Toolchain installation requires Linux x86_64")
    manifest = json.loads((HERE / "sources.json").read_text())
    all_sources = [manifest["rusty_v8"], manifest["v8"], *manifest["dependencies"]]
    for source in all_sources:
        validate_source(source)
    checkout(manifest["rusty_v8"], SOURCES)
    if bindings_only:
        return
    checkout(manifest["v8"], SOURCES / "v8")
    parsed = read_deps(SOURCES / "v8" / "DEPS")
    dependencies = parsed["deps"]
    for source in manifest["dependencies"]:
        dependency = dependencies[source["path"]]
        url = dependency if isinstance(dependency, str) else dependency["url"]
        if url != source["repository"] + "@" + source["revision"]:
            raise ValueError(f"Pin differs from V8 DEPS: {source['path']}")
        checkout(source, SOURCES / source["path"])
    for component in ("build", "v8", "rusty_v8"):
        directory = SOURCES if component == "rusty_v8" else SOURCES / component
        for patch in sorted((HERE / "patches" / component).glob("*.patch")):
            apply_patch(directory, patch)
    # Upstream tooling imports this module. Give it parsed data, without exec(DEPS).
    (SOURCES / "tools" / "v8-deps.json").write_text(json.dumps(parsed))
    (SOURCES / "tools" / "v8_deps.py").write_text(
        "import json\nfrom pathlib import Path\n"
        'data = json.loads(Path(__file__).with_name("v8-deps.json").read_text())\n'
        'deps = data["deps"]\n'
        'def Var(name):\n    return data["vars"][name]\n'
    )
    if toolchains:
        for name in ("rust-toolchain", "llvm-libclang"):
            directory = SOURCES / "third_party" / name
            url = download_toolchain(dependencies["third_party/" + name], directory)
            if name == "rust-toolchain":
                (directory / ".rusty_v8_version").write_text(url)
    version_header = (SOURCES / "v8" / "include" / "v8-version.h").read_text()
    parts = [re.search(r"#define V8_" + key + r"\s+(\d+)", version_header).group(1)
             for key in ("MAJOR_VERSION", "MINOR_VERSION", "BUILD_NUMBER", "PATCH_LEVEL")]
    if ".".join(parts) != manifest["v8_version"]:
        raise ValueError("V8 source version differs from the manifest")
    provenance = {**manifest, "patches": {
        str(p.relative_to(HERE)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted((HERE / "patches").rglob("*.patch"))
    }}
    (SOURCES.parent / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bindings-only", action="store_true",
                        help="fetch only Rust bindings for dependency resolution; not a build")
    parser.add_argument("--toolchains", action="store_true",
                        help="also install checksum-verified Linux x64 Rust and libclang tools")
    args = parser.parse_args()
    prepare(args.bindings_only, args.toolchains)
