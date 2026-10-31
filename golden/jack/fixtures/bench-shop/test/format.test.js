import { test } from 'node:test';
import assert from 'node:assert/strict';
import { formatMoney } from '../src/index.js';

test('formats with two decimals and the euro sign', () => {
  assert.equal(formatMoney(12.5), '12.50 €');
  assert.equal(formatMoney(0), '0.00 €');
});
