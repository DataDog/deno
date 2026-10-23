# Copyright 2018-2026 the Deno authors. MIT license.

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import call, patch

from deps import read_deps
from prepare import HERE, fetch_revision, validate_source


class PreparationTest(unittest.TestCase):
    def test_fetch_retries_same_revision_after_disconnect(self):
        revision = "a" * 40
        destination = Path("checkout")
        with patch("prepare.run", side_effect=[subprocess.CalledProcessError(128, "git"), None]) as run, \
                patch("prepare.time.sleep") as sleep:
            fetch_revision(revision, destination)
        expected = call("git", "fetch", "--depth=1", "origin", revision, cwd=destination)
        self.assertEqual(run.call_args_list, [expected, expected])
        sleep.assert_called_once_with(2)

    def test_fetch_exhausted_retries_propagate_failure(self):
        failure = subprocess.CalledProcessError(128, "git")
        with patch("prepare.run", side_effect=failure) as run, \
                patch("prepare.time.sleep") as sleep:
            with self.assertRaises(subprocess.CalledProcessError) as raised:
                fetch_revision("a" * 40, Path("checkout"))
        self.assertIs(raised.exception, failure)
        self.assertEqual(run.call_count, 3)
        self.assertEqual(sleep.call_args_list, [call(2), call(4)])

    def test_source_manifest_is_pinned(self):
        manifest = json.loads((HERE / "sources.json").read_text())
        for source in [manifest["rusty_v8"], manifest["bindgen"], manifest["v8"], *manifest["dependencies"]]:
            validate_source(source)
        paths = [source["path"] for source in manifest["dependencies"]]
        self.assertEqual(len(paths), len(set(paths)))

    def test_reject_missing_or_mutable_revision(self):
        for revision in (None, "", "main", "0" * 40):
            with self.subTest(revision=revision), self.assertRaises(ValueError):
                validate_source({"repository": "https://github.com/v8/v8.git", "revision": revision})

    def test_reject_checkout_escape(self):
        for path in (None, "", ".", "../outside", "/tmp/outside"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                validate_source({"repository": "https://github.com/v8/v8.git",
                                 "revision": "a" * 40, "path": path})

    def test_manifest_expressions_are_data_only(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "DEPS"
            marker = Path(directory) / "executed"
            source.write_text(
                "vars = {'repo': Str('https://example.com/repo')}\n"
                "deps = {'build': Var('repo') + '@' + 'abc'}\n"
            )
            self.assertEqual(read_deps(source), {
                "vars": {"repo": "https://example.com/repo"},
                "deps": {"build": "https://example.com/repo@abc"},
            })
            source.write_text(f"deps = {{'build': open({str(marker)!r}, 'w')}}\n")
            with self.assertRaises(ValueError):
                read_deps(source)
            self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
