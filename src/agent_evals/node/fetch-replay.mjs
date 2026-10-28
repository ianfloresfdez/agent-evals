// Preloaded with `node --import` into a Node process under test (e.g. an MCP server) so its HTTP calls are
// recorded once and replayed afterwards. The clock is frozen at recording time, so "posted 3 days ago" and
// max-age filters give the same answer on every replay.
//
//   AGENT_EVALS_CASSETTE       path of the cassette JSON (gzipped when it ends in .gz)
//   AGENT_EVALS_CASSETTE_MODE  replay (default, misses fail) | record (always live) | auto (replay, record misses)
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';
import { gunzipSync, gzipSync } from 'node:zlib';

const file = process.env.AGENT_EVALS_CASSETTE;
const mode = process.env.AGENT_EVALS_CASSETTE_MODE ?? 'replay';

if (file) {
  const gz = file.endsWith('.gz');
  const read = () => {
    const raw = readFileSync(file);
    return JSON.parse((gz ? gunzipSync(raw) : raw).toString('utf8'));
  };
  const cassette = existsSync(file) ? read() : { frozenAt: Date.now(), entries: {} };
  const frozenAt = cassette.frozenAt;
  Date.now = () => frozenAt;

  const save = () => {
    mkdirSync(dirname(file), { recursive: true });
    const sorted = Object.fromEntries(Object.entries(cassette.entries).sort(([a], [b]) => a.localeCompare(b)));
    const json = JSON.stringify({ ...cassette, entries: sorted }, null, 1);
    writeFileSync(file, gz ? gzipSync(json) : json);
  };
  const respond = (e) => new Response(e.status === 204 || e.status === 304 ? null : e.body, { status: e.status, headers: e.headers });

  const realFetch = globalThis.fetch;
  globalThis.fetch = async (input, init = {}) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    const key = `${(init.method ?? 'GET').toUpperCase()} ${url}`;
    const hit = cassette.entries[key];
    if (hit && mode !== 'record') return respond(hit);
    if (mode === 'replay') throw new Error(`not in cassette: ${key}`);
    const res = await realFetch(input, init);
    const entry = { status: res.status, headers: { 'content-type': res.headers.get('content-type') ?? 'text/plain' }, body: await res.text() };
    cassette.entries[key] = entry;
    save();
    return respond(entry);
  };
}
