import { test } from 'node:test';
import assert from 'node:assert/strict';
import { sum } from '../src/index.js';

// Pre-existing failure: the pipeline must not ship on top of a red suite.
test('sum handles string input', () => {
  assert.equal(sum('2', 3), 5);
});
