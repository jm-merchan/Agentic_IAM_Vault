import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import test from "node:test";

const source = await readFile(new URL("../app/trace_flow.js", import.meta.url), "utf8");
const component = (await import("data:text/javascript;base64," + Buffer.from(source).toString("base64"))).default;
function view() {
  const vm = {flow: {calls: [{id: "a"}, {id: "b"}]}, traceId: "trace", $nextTick() {}};
  Object.assign(vm, component.data.call(vm));
  for (const [key, method] of Object.entries(component.methods)) vm[key] = method.bind(vm);
  for (const [key, getter] of Object.entries(component.computed))
    Object.defineProperty(vm, key, {get: getter.bind(vm)});
  return vm;
}

test("changing step clears values and ignores the previous in-flight response", async () => {
  const vm = view();
  let resolve;
  const previous = globalThis.fetch;
  globalThis.fetch = () => new Promise(r => {resolve = r;});
  try {
    const loading = vm.revealSensitive();
    vm.select({id: "b"});
    resolve({ok: true, json: async () => ({sections: [{key: "response", value: "OLD_SECRET"}],
      expires_at: Date.now() / 1000 + 60})});
    await loading;
    assert.equal(vm.inspection, null);
    assert.equal(vm.inspecting, false);
    assert.equal(vm.selected.id, "b");
  } finally {globalThis.fetch = previous; vm.hideSensitive();}
});

test("reveal uses same-origin no-store; hiding and filtering discard the payload", async () => {
  const vm = view(), previous = globalThis.fetch;
  globalThis.fetch = async (url, options) => {
    assert.equal(url, "/traces/trace/steps/a/sensitive");
    assert.equal(options.credentials, "same-origin");
    assert.equal(options.cache, "no-store");
    assert.equal(options.headers["X-Lumen-Language"], "es");
    return {ok: true, json: async () => ({sections: [{key: "response", value: "CANARY"}],
      expires_at: Date.now() / 1000 + 60})};
  };
  try {
    await vm.revealSensitive();
    assert.equal(vm.section.value, "CANARY");
    vm.changeFilter();
    assert.equal(vm.inspection, null);
    assert.equal(vm.sectionKey, "");
  } finally {globalThis.fetch = previous; vm.hideSensitive();}
});

test("expired session displays the denial without retaining a secret payload", async () => {
  const vm = view(), previous = globalThis.fetch;
  globalThis.fetch = async () => ({ok: false, json: async () => ({message: "Sesión caducada"})});
  try {
    await vm.revealSensitive();
    assert.equal(vm.inspectionError, "Sesión caducada");
    assert.equal(vm.inspection, null);
    assert.equal(vm.loading, false);
  } finally {globalThis.fetch = previous; vm.hideSensitive();}
});

test("English diagram labels and formatting keep captured values intact", () => {
  const vm = view();
  vm.locale = "en-US";
  vm.messages = {"PASO {number} DE {count}": "STEP {number} OF {count}", "Copiar valor": "Copy value"};
  assert.equal(vm.t("PASO {number} DE {count}", {number: 2, count: 4}), "STEP 2 OF 4");
  assert.equal(vm.ms(1234.56), "1,234.56 ms");
  assert.equal(vm.format("Copiar valor"), "Copiar valor");
  assert.equal(vm.format({client_secret: "Copiar valor"}), '{\n  "client_secret": "Copiar valor"\n}');
  vm.messages = {};
  vm.locale = "es-ES";
  assert.equal(vm.t("Copiar valor"), "Copiar valor");
  assert.equal(vm.ms(34.56), "34,56 ms");
});
