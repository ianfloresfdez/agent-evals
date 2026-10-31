import { test } from 'node:test';
import assert from 'node:assert/strict';
import { Catalog, Cart, Orders, SHIPPING_COST, FREE_SHIPPING_FROM } from '../src/index.js';

function cart(qty) {
  const c = new Catalog();
  c.add({ sku: 'TEE', name: 'T-shirt', price: 20, stock: 10 });
  const cart = new Cart(c);
  if (qty) cart.add('TEE', qty);
  return { cart, orders: new Orders(c) };
}

test('constants are exported', () => {
  assert.equal(SHIPPING_COST, 4.99);
  assert.equal(FREE_SHIPPING_FROM, 50);
});

test('below 50 € with tax pays shipping, included in the total', () => {
  const s = cart(1).cart.summary(); // 20 + 4.20 tax = 24.20
  assert.equal(s.shipping, 4.99);
  assert.equal(s.total, 29.19);
});

test('50 € or more with tax ships free', () => {
  const s = cart(3).cart.summary(); // 60 + 12.60 = 72.60
  assert.equal(s.shipping, 0);
  assert.equal(s.total, 72.6);
});

test('the threshold looks at subtotal plus tax, not the subtotal alone', () => {
  const c = new Catalog();
  c.add({ sku: 'X', name: 'X', price: 41.33, stock: 1 }); // 41.33 + 8.68 = 50.01
  const k = new Cart(c);
  k.add('X');
  assert.equal(k.summary().shipping, 0);
});

test('an empty cart has no shipping, and orders carry it', () => {
  assert.equal(cart(0).cart.summary().shipping, 0);
  const { cart: k, orders } = cart(1);
  const o = orders.place(k, 'ana');
  assert.equal(o.shipping, 4.99);
  assert.equal(o.total, 29.19);
});
