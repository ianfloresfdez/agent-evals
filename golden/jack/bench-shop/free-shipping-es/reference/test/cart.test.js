import { test } from 'node:test';
import assert from 'node:assert/strict';
import { Cart } from '../src/index.js';
import { shop } from './helpers.js';

test('summary adds tax to the subtotal', () => {
  const cart = new Cart(shop());
  cart.add('MUG', 2);
  cart.add('TEE');
  const s = cart.summary();
  assert.equal(s.subtotal, 36);
  assert.equal(s.tax, 7.56);
  assert.equal(s.shipping, 4.99); // 43.56 with tax, under the free-shipping threshold
  assert.equal(s.total, 48.55);
});

test('adding the same product twice sums the quantity', () => {
  const cart = new Cart(shop());
  cart.add('MUG');
  cart.add('MUG', 3);
  assert.equal(cart.lines()[0].qty, 4);
});

test('invalid quantities and unknown products are rejected', () => {
  const cart = new Cart(shop());
  assert.throws(() => cart.add('MUG', 0), RangeError);
  assert.throws(() => cart.add('NOPE'), /Unknown product/);
});

test('large quantities get the bulk discount', () => {
  const cart = new Cart(shop());
  cart.add('MUG', 20);
  assert.equal(cart.summary().subtotal, 144);
});
