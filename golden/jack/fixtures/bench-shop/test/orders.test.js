import { test } from 'node:test';
import assert from 'node:assert/strict';
import { Cart, Orders } from '../src/index.js';
import { shop } from './helpers.js';

test('placing an order empties the cart', () => {
  const catalog = shop();
  const cart = new Cart(catalog);
  const orders = new Orders(catalog);
  cart.add('MUG');
  const o = orders.place(cart, 'ana');
  assert.equal(o.status, 'placed');
  assert.equal(o.total, 9.68);
  assert.equal(cart.lines().length, 0);
});

test('empty carts cannot be ordered and orders cancel once', () => {
  const catalog = shop();
  const orders = new Orders(catalog);
  assert.throws(() => orders.place(new Cart(catalog), 'ana'), /empty/);
  const cart = new Cart(catalog);
  cart.add('TEE');
  const o = orders.place(cart, 'ana');
  orders.cancel(o.id);
  assert.throws(() => orders.cancel(o.id), /already cancelled/);
});
