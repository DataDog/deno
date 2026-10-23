// Copyright 2018-2026 the Deno authors. MIT license.
// Run by verify.py with the same permission and V8 flags as Synthetics.
import assert from "node:assert/strict";
import vm from "node:vm";

assert.equal(Deno.version.v8.split("-")[0], "15.6.75.19");
assert.throws(() => Function("return 42"), EvalError);

// CVE-2026-11645: exercise the native property transition in a new context.
// New VM contexts can enable string compilation independently of the CLI flag.
const actual = vm.runInNewContext(`(() => {
  const key = "AA";
  let value = 2;
  class C extends Function { [key] = value; }
  const first = new C("'use strict'");
  value = 1.1;
  const second = new C("'use strict'");
  return [first[key], second[key]];
})()`);
assert.equal(actual[0], 2);
assert.equal(actual[1], 1.1);

for (const name of ["read", "write", "net", "env", "run", "sys", "ffi"]) {
  assert.equal((await Deno.permissions.query({ name })).state, "denied");
}
await assert.rejects(
  Deno.readTextFile("/etc/hostname"),
  Deno.errors.NotCapable,
);
assert.throws(() => Deno.env.get("PATH"), Deno.errors.NotCapable);
assert.throws(
  () => new Deno.Command("true").outputSync(),
  Deno.errors.NotCapable,
);
// deno-lint-ignore no-console
console.log(
  "upstream V8 version, VM-context regression, and permission checks passed",
);
