import { test } from 'node:test';
import assert from 'node:assert/strict';
import { lineTotal, totals } from '../src/index.js';

test('exactly BULK_MIN_QTY units get the discount', () => {
  assert.equal(lineTotal(4, 10), 36);
  assert.equal(totals([{ price: 4, qty: 10 }]).subtotal, 36);
});

test('below the threshold pays full price, above keeps the discount', () => {
  assert.equal(lineTotal(4, 9), 36);
  assert.equal(lineTotal(4, 11), 39.6);
});
