# Copyright 2018-2026 the Deno authors. MIT license.

import tempfile
import unittest
from pathlib import Path

from cache import RECIPE_FILES, REQUIRED_ENV, TOOLS, cache_keys


class CacheTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.manifests = ["Cargo.toml", "libs/core/Cargo.toml"]
        for path in [*RECIPE_FILES, *self.manifests]:
            file = self.root / path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text("pinned input\n")
        for component in ("build", "v8", "rusty_v8", "bindgen"):
            file = self.root / "tools/upstream_v8/patches" / component / "test.patch"
            file.parent.mkdir(parents=True)
            file.write_text("patch\n")
        self.environment = {
            "RUNNER_OS": "Linux", "RUNNER_ARCH": "X64", "ImageOS": "ubuntu24",
            "ImageVersion": "20261023.1", "GITHUB_SHA": "a" * 40,
            "CARGO_PROFILE_RELEASE_LTO": "thin", "CARGO_PROFILE_RELEASE_CODEGEN_UNITS": "8",
            "RUSTC_WRAPPER": "sccache",
        }
        self.versions = {name: f"{name} version 1" for name in TOOLS}

    def keys(self):
        return cache_keys(self.root, self.environment, self.versions, self.manifests)

    def test_reuse_configuration_across_commits(self):
        first = self.keys()
        self.environment["GITHUB_SHA"] = "b" * 40
        second = self.keys()
        for kind in ("sccache", "cargo"):
            self.assertEqual(first[f"{kind}_prefix"], second[f"{kind}_prefix"])
            self.assertNotEqual(first[f"{kind}_key"], second[f"{kind}_key"])
            self.assertTrue(second[f"{kind}_key"].startswith(first[f"{kind}_prefix"]))

    def test_reject_incomplete_or_zero_environment(self):
        for name in REQUIRED_ENV:
            original = self.environment.pop(name)
            for value in (None, "", " ", "0", "0" * 40):
                with self.subTest(name=name, value=value):
                    if value is not None:
                        self.environment[name] = value
                    with self.assertRaises(ValueError):
                        self.keys()
            self.environment[name] = original

    def test_reject_incomplete_tool_versions(self):
        for name in TOOLS:
            original = self.versions.pop(name)
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.keys()
            self.versions[name] = original

    def test_reject_invalid_commit_and_platform(self):
        for revision in ("main", "a" * 7, "a" * 39 + "\n"):
            self.environment["GITHUB_SHA"] = revision
            with self.subTest(revision=revision), self.assertRaises(ValueError):
                self.keys()
        self.environment["GITHUB_SHA"] = "a" * 40
        self.environment["RUNNER_ARCH"] = "ARM64"
        with self.assertRaises(ValueError):
            self.keys()

    def test_build_inputs_invalidate_restore_prefix(self):
        original = self.keys()["cargo_prefix"]
        for path in [*RECIPE_FILES, *self.manifests, "tools/upstream_v8/patches/rusty_v8/test.patch"]:
            file = self.root / path
            before = file.read_text()
            file.write_text(before + "changed\n")
            with self.subTest(path=path):
                self.assertNotEqual(original, self.keys()["cargo_prefix"])
            file.write_text(before)
        self.versions["rustc"] = "rustc version 2"
        self.assertNotEqual(original, self.keys()["cargo_prefix"])

    def test_flags_invalidate_restore_prefix(self):
        original = self.keys()["sccache_prefix"]
        self.environment["GN_ARGS"] = "v8_enable_pointer_compression=true"
        self.assertNotEqual(original, self.keys()["sccache_prefix"])
        self.environment["GN_ARGS"] = ""
        with self.assertRaises(ValueError):
            self.keys()

    def test_reject_missing_empty_or_escaping_files(self):
        file = self.root / "Cargo.lock"
        file.unlink()
        with self.assertRaises(FileNotFoundError):
            self.keys()
        file.write_text("")
        with self.assertRaises(ValueError):
            self.keys()
        file.write_text("lockfile\n")
        self.manifests.append("../Cargo.toml")
        with self.assertRaises(ValueError):
            self.keys()

    def test_reject_missing_patches_and_manifests(self):
        (self.root / "tools/upstream_v8/patches/v8/test.patch").unlink()
        with self.assertRaises(ValueError):
            self.keys()
        self.manifests.clear()
        with self.assertRaises(ValueError):
            self.keys()


if __name__ == "__main__":
    unittest.main()
