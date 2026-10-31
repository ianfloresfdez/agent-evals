import { test } from 'node:test';
import assert from 'node:assert/strict';
import { formatMoney } from '../src/index.js';

test('groups thousands with commas', () => {
  assert.equal(formatMoney(1234.5), '1,234.50 €');
  assert.equal(formatMoney(1234567.891), '1,234,567.89 €');
});

test('small amounts are unchanged', () => {
  assert.equal(formatMoney(12.5), '12.50 €');
  assert.equal(formatMoney(999.999), '1,000.00 €');
});

test('negative amounts keep the sign in front', () => {
  assert.equal(formatMoney(-5), '-5.00 €');
  assert.equal(formatMoney(-1500), '-1,500.00 €');
});
