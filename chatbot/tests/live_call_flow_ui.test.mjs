import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';

const source = await readFile(new URL('../app/live_call_flow.js', import.meta.url), 'utf8');
const component = (await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'))).default;
function view() {
  const vm = {$nextTick() {}};
  Object.assign(vm, component.data.call(vm));
  for (const [key, method] of Object.entries(component.methods)) vm[key] = method.bind(vm);
  return vm;
}
const snapshot = (traceId, calls) => ({traceId, authenticated:true, calls,
  actors:[{id:'lumen',name:'Lumen'}, {id:'vault',name:'Vault'}]});

test('completion updates one arrow in place; repeat polling does not duplicate it', () => {
  const vm = view();
  vm.sync(snapshot('one', [{id:'a',target:'vault',active:true}]));
  const arrow = vm.calls[0];
  vm.sync(snapshot('one', [{id:'a',target:'vault',active:false,http_status:200}]));
  assert.equal(vm.calls.length, 1);
  assert.equal(vm.calls[0], arrow);
  assert.equal(arrow.http_status, 200);
  assert.equal(arrow.active, false);
});

test('new execution and expired session clear previous arrows and actor columns', () => {
  const vm = view();
  vm.sync(snapshot('one', [{id:'a',target:'vault'}]));
  vm.sync({traceId:'two',authenticated:true,calls:[],actors:[{id:'lumen',name:'Lumen'}]});
  assert.equal(vm.calls.length, 0);
  assert.equal(vm.actors.length, 1);
  vm.expanded = true;
  vm.sync({traceId:'',authenticated:false,calls:[],actors:[]});
  assert.equal(vm.actors.length, 0);
  assert.equal(vm.expanded, false);
});

test('actor positions stay stable when a slower earlier span arrives', () => {
  const vm = view();
  vm.sync(snapshot('one', [{id:'b',target:'vault'}]));
  vm.sync({traceId:'one',authenticated:true,calls:[{id:'a',target:'verify'},{id:'b',target:'vault'}],
    actors:[{id:'lumen',name:'Lumen'},{id:'verify',name:'IBM Verify'},{id:'vault',name:'Vault'}]});
  assert.deepEqual(vm.actors.map(a => a.id), ['lumen','vault','verify']);
});

test('mobile panel shrinks above the composer or docks below it without hiding its heading', () => {
  const previousWindow = globalThis.window, previousDocument = globalThis.document;
  const vm = view();
  vm.$el = {getBoundingClientRect: () => ({left:16,right:374})};
  vm.$refs = {scroll:{clientWidth:356}};
  let input = {top:379,bottom:498,left:16,right:374};
  globalThis.window = {innerHeight:844,visualViewport:{height:844,offsetTop:0}};
  globalThis.document = {querySelector: () => ({getBoundingClientRect: () => input})};
  try {
    vm.place();
    assert.ok(844 - vm.bottom - vm.panelHeight - 54 >= 16);
    assert.ok(844 - vm.bottom < input.top);
    input = {...input,top:60,bottom:179};
    vm.place();
    assert.ok(844 - vm.bottom - vm.panelHeight - 54 > input.bottom);
  } finally {globalThis.window = previousWindow; globalThis.document = previousDocument;}
});
