import { test } from 'node:test';
import assert from 'node:assert/strict';
import { Catalog } from '../src/index.js';

test('adds products and rejects duplicates', () => {
  const c = new Catalog();
  c.add({ sku: 'A', name: 'A', price: 1 });
  assert.throws(() => c.add({ sku: 'A', name: 'A', price: 1 }), /already exists/);
});

test('unknown products throw', () => {
  assert.throws(() => new Catalog().get('nope'), /Unknown product/);
});

test('negative prices are rejected', () => {
  assert.throws(() => new Catalog().add({ sku: 'A', name: 'A', price: -1 }), RangeError);
});
