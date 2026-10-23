# Datadog Deno with upstream stable V8

This branch builds Deno 2.9.8 with **V8 15.6.75.19**, the exact V8 commit in
Chrome **156.0.8078.47 Stable for Linux**. The selection was verified against
[Chromium Dash](https://chromiumdash.appspot.com/fetch_releases?channel=Stable&platform=Linux&num=1)
on October 22, 2026. `sources.json` records immutable source revisions. A normal
Cargo build on this branch fails until those sources are prepared; it cannot
silently use the old prebuilt V8 archive.

## Build and package

The supported packaging target is native Linux x86_64, with Ubuntu 24.04 as the
CI builder. Install Rust through rustup (the repository pins its version),
Python 3.12+, Git, curl, a C/C++ toolchain, lld, CMake, Ninja, pkg-config,
libglib2.0-dev and protobuf-compiler. Allocate substantial disk space for both
V8 and Deno. The workflow removes unused SDKs on its disposable runner.

From the repository root:

```sh
python3 -m unittest discover -s tools/upstream_v8 -p '*_test.py'
python3 tools/upstream_v8/prepare.py --toolchains
export LIBCLANG_PATH="$PWD/target/upstream-v8/rusty_v8/third_party/llvm-libclang/lib"
export PATH="$PWD/target/upstream-v8/tools/gn:$PWD/target/upstream-v8/tools/ninja:$PATH"
cargo build --release --locked -p deno
cargo test --release --locked -p deno_core --lib
python3 tools/upstream_v8/verify.py
```

`.cargo/config.toml` forces `V8_FROM_SOURCE=1`. The preparation step checks out
the pinned Rust bindings and upstream engine, checks out the matching V8 DEPS
revisions, applies the patches under `patches/`, and verifies the engine
version. The DEPS parser accepts literal data and `Var`/`Str` expressions
without executing the manifest. The Linux Rust and libclang toolchain downloads
are checked against the SHA-256 digests in that pinned manifest.

The final ZIP, checksum and source/patch provenance are written under
`target/upstream-v8/package/`. The dedicated **Datadog upstream V8** workflow
runs on pushes to `julesdt/upstream-v8-stable` and relevant PR changes,
including draft PRs. It retains packages for 30 days. Promote a validated
package to durable internal artifact storage before pinning it in a Synthetics
image; this workflow does not publish to upstream Deno's storage or deploy a
service.

## Patch ownership

The Rust binding crate is pinned to upstream commit
`55ca54ea97dbfcf80c5457924861b681bd83def2` (crate version 152.2.0). That crate
version identifies the binding API, not the engine bundled by this branch. The
engine is upstream V8 commit `392e44423f46d75904da712fadea4c7d5d97967f`.

`patches/build/0001-rust-embedder-build.patch` ports the build adjustments from
denoland/chromium_build `fab0ea1e..2c779f9` onto the Chromium build revision
required by this V8 release. These include Cargo embedding support and
debug-info settings. The bindgen adaptation removes Cargo's ambient TARGET so
GN's explicit target arguments determine the bindings.

`patches/rusty_v8/0001-v8-15.6-api.patch` adapts removed C++ APIs and accessor
callbacks, and uses the now-unconditional garbage-collected microtask queues.
Heap termination is left to the V8 heap destructor, as required by this engine.

The Deno changes use scoped local handles for the newer binding API, retain
owned microtask queue handles in Node VM contexts, and update property callback
return types. CI runs the core Rust tests and checks both Node VM context
creation paths with explicitly owned microtask queues.

For the next update, resolve another stable V8 revision, regenerate and review
the dependency pins, port the embedding patches, update the Cargo lockfile if
the binding API changes, and pass the native build and runtime tests. Never
change only the version string or substitute a newer static archive for older
bindings.

## Validation scope

V8 15.6 removes inspector live editing (`Debugger.setScriptSource`). The retired
`--inspector-live-edit` startup flag is removed, and Deno's inspector-based hot
module replacement is not supported by this custom runtime.

Packaging requires the expected runtime V8 version, the CVE-2026-11645 property
regression inside a Node VM context, and deny-permission checks with Synthetics'
jitless, single-threaded and 27 MiB heap configuration. This is a build gate,
not full Synthetics integration or a claim that the runtime has no
vulnerabilities. Before deployment, run both Synthetics execution routes, all
three script modes, vendored dependencies and timeout/memory tests against the
rebuilt worker image.
