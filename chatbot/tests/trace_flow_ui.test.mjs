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

test("Vault explanation is on demand, isolated from sensitive capture and cleared on collapse", async () => {
  const vm = view(), previous = globalThis.fetch;
  vm.flow.calls[0].target = 'vault';
  vm.inspection = {sections: [{key: 'secret', value: 'KEEP_SEPARATE'}]};
  let calls = 0;
  globalThis.fetch = async (url, options) => {
    calls++;
    assert.equal(url, '/traces/trace/steps/a/vault-decision');
    assert.equal(options.credentials, 'same-origin');
    assert.equal(options.cache, 'no-store');
    return {ok: true, json: async () => ({audit_state: 'matched', mode: 'obo', evidence: {policy_allowed: true}})};
  };
  try {
    assert.equal(vm.decisionOpen, false);
    await vm.toggleVaultDecision();
    assert.equal(vm.decisionOpen, true);
    assert.equal(vm.vaultDecision.mode, 'obo');
    assert.equal(vm.inspection.sections[0].value, 'KEEP_SEPARATE');
    await vm.toggleVaultDecision();
    assert.equal(vm.vaultDecision, null);
    assert.equal(calls, 1);
    vm.select(vm.flow.calls[1]);
    await vm.toggleVaultDecision();
    assert.equal(calls, 1); // No audit lookup for another service.
  } finally {globalThis.fetch = previous; vm.closeVaultDecision();}
});

test("Vault explanation ignores late responses after changing step or filter", async () => {
  const vm = view(), previous = globalThis.fetch;
  vm.flow.calls.forEach(call => {call.target = 'vault';});
  let resolve;
  globalThis.fetch = () => new Promise(r => {resolve = r;});
  try {
    const pending = vm.toggleVaultDecision();
    vm.select(vm.flow.calls[1]);
    resolve({ok: true, json: async () => ({mode: 'OLD_CALL'})});
    await pending;
    assert.equal(vm.vaultDecision, null);
    assert.equal(vm.decisionOpen, false);
    const next = vm.toggleVaultDecision();
    vm.filter = 'all'; vm.changeFilter();
    resolve({ok: true, json: async () => ({mode: 'OLD_FILTER'})});
    await next;
    assert.equal(vm.vaultDecision, null);
    assert.equal(vm.decisionLoading, false);
  } finally {globalThis.fetch = previous; vm.closeVaultDecision();}
});

test("Vault audit errors can be retried without repeating the Vault operation", async () => {
  const vm = view(), previous = globalThis.fetch;
  vm.flow.calls[0].target = 'vault'; let calls = 0;
  vm.messages = {'No se pudo consultar la auditoría.': 'Audit unavailable'};
  globalThis.fetch = async (url, options) => {
    assert.ok(url.endsWith('/vault-decision'));
    assert.equal(options.method, undefined);
    if (++calls === 1) throw new Error('offline');
    return {ok: true, json: async () => ({mode: 'native', audit_state: 'matched'})};
  };
  try {
    await vm.toggleVaultDecision();
    assert.equal(vm.decisionError, 'Audit unavailable');
    await vm.retryVaultDecision();
    assert.equal(vm.vaultDecision.mode, 'native');
    assert.equal(vm.decisionError, '');
  } finally {globalThis.fetch = previous; vm.closeVaultDecision();}
});

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

test("workbench opens without sending and reset preserves the exact captured body", async () => {
  const vm = view(); let calls = 0; const previous = globalThis.fetch;
  const request = {id: "http.request.1", kind: "http", method: "POST", url: "https://api.example/v1",
    headers: {authorization: "Bearer CANARY"}, body: '{"messages":[{"content":"energía"}]}'};
  globalThis.fetch = async () => { calls++; return {ok:true, json:async () => ({sections:[], requests:[request], expires_at:Date.now()/1000+60})}; };
  try {
    await vm.openWorkbench();
    assert.equal(calls, 1); assert.equal(vm.workbench, true);
    assert.equal(vm.draft.body, request.body);
    vm.draft.body = "edited"; vm.loadRequest(request.id);
    assert.equal(vm.draft.body, request.body);
    vm.hideSensitive(); assert.equal(vm.draft, null); assert.equal(vm.workbench, false);
  } finally {globalThis.fetch = previous; vm.hideSensitive();}
});

test("sending uses the edited request once; changing steps discards its response", async () => {
  const vm = view(); const previous = globalThis.fetch; let resolve, calls = 0;
  vm.inspection = {requests:[{id:"http.request.1",kind:"http",method:"POST",url:"https://api.example/v1",headers:{authorization:"Bearer CANARY"},body:"original"}]};
  vm.controller = new AbortController(); vm.loadRequest("http.request.1"); vm.draft.body = "edited";
  globalThis.fetch = (url, options) => {
    calls++; assert.equal(options.method, "POST"); assert.equal(options.credentials, "same-origin");
    assert.equal(JSON.parse(options.body).body, "edited");
    return new Promise(r => {resolve = r;});
  };
  try {
    const sending = vm.sendRequest(); await vm.sendRequest(); assert.equal(calls, 1);
    vm.select({id:"b"});
    resolve({ok:true,json:async () => ({status_code:200,body:"NEW_SECRET"})}); await sending;
    assert.equal(vm.replayResult,null); assert.equal(vm.draft,null);
  } finally {globalThis.fetch = previous; vm.hideSensitive();}
});

test("personal explanation distinguishes Verify token issuance from Vault authorization", () => {
  const vm = view();
  vm.flow.calls[0] = {id: 'a', target: 'verify', http_status: 200, personal: {path_matches_owner: true}};
  assert.match(vm.personalOutcome, /no demuestra acceso/);
  vm.flow.calls[0].target = 'vault';
  assert.match(vm.personalOutcome, /Vault ha permitido esta operación/);
  vm.flow.calls[0].personal.path_matches_owner = false;
  assert.match(vm.personalOutcome, /permitido una ruta ajena/);
  vm.flow.calls[0].http_status = 403;
  assert.match(vm.personalOutcome, /Vault ha denegado/);
  vm.flow.calls[0].http_status = 404;
  assert.match(vm.personalOutcome, /no confirma acceso ni aislamiento/);
});

test("personal panel and outcome explanations have English translations", async () => {
  const translations = JSON.parse(await readFile(new URL('../app/translations_en.json', import.meta.url), 'utf8'));
  const panel = component.template.split('class="tf-rar-panel tf-personal"')[1].split('<section v-if="selected?.rar"')[0];
  for (const match of panel.matchAll(/t\('([^']+)'\)/g))
    assert.ok(translations[match[1]], 'Missing English translation: ' + match[1]);
  const vm = view(); vm.messages = translations;
  for (const target of ['verify', 'vault']) for (const code of [200, 403, 404]) for (const same of [true, false]) {
    vm.flow.calls[0] = {id: 'a', target, http_status: code, personal: {path_matches_owner: same}};
    assert.notEqual(vm.t(vm.personalOutcome), vm.personalOutcome);
  }
});
