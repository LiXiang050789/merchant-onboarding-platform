const assert = require('node:assert/strict');
const fs = require('node:fs');
const Module = require('node:module');
const path = require('node:path');
const {test} = require('node:test');
const ts = require('typescript');
const {QueryClient, QueryObserver} = require('@tanstack/query-core');

test('status event during first fetch cannot leave a fresh stale result', async () => {
  const filename = path.join(__dirname, 'realtime.ts');
  const source = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022}
  }).outputText;
  const compiled = new Module(filename, module);
  compiled.filename = filename;
  compiled.paths = module.paths;
  compiled.require = name => name === '@/shared/api/client'
    ? {apiBase: () => 'http://test', getAccessToken: () => 'unit-test'}
    : require(name);
  compiled._compile(source, filename);
  let socket;
  class TestSocket {
    constructor() { socket = this; }
    close() {}
  }
  const originalSocket = global.WebSocket;
  global.WebSocket = TestSocket;
  const client = new QueryClient({defaultOptions: {queries: {retry: false, gcTime: 0}}});
  const key = ['forms', 'shanghai', 'all'];
  let calls = 0;
  let release;
  const first = new Promise(resolve => {release = resolve;});
  const observer = new QueryObserver(client, {
    queryKey: key, staleTime: 30000,
    queryFn: () => ++calls === 1 ? first : Promise.resolve({status: 'validated'})
  });
  const unsubscribe = observer.subscribe(() => {});
  const stop = compiled.exports.startRealtime(client);
  try {
    assert.equal(calls, 1);
    assert.equal(client.getQueryData(key), undefined);
    socket.onmessage({data: JSON.stringify({seq:1,type:'form.status_changed',payload:{status:'validated'}})});
    release({status:'submitted'});
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(calls, 2, 'event must start a new request even when the first fetch has no cached data');
    assert.deepEqual(client.getQueryData(key), {status:'validated'});
    assert.equal(client.getQueryState(key).isInvalidated, false);
  } finally {
    stop(); unsubscribe(); client.clear(); global.WebSocket = originalSocket;
  }
});
