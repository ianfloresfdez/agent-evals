import { test } from 'node:test';
import assert from 'node:assert/strict';
import { Catalog, Cart, Orders, OutOfStockError } from '../src/index.js';

function setup() {
  const catalog = new Catalog();
  catalog.add({ sku: 'MUG', name: 'Mug', price: 8, stock: 5 });
  catalog.add({ sku: 'TEE', name: 'T-shirt', price: 20, stock: 1 });
  return { catalog, cart: new Cart(catalog), orders: new Orders(catalog) };
}

test('placing an order takes the units out of stock', () => {
  const { catalog, cart, orders } = setup();
  cart.add('MUG', 3);
  orders.place(cart, 'ana');
  assert.equal(catalog.get('MUG').stock, 2);
});

test('not enough stock throws OutOfStockError naming the sku, and reserves nothing', () => {
  const { catalog, cart, orders } = setup();
  cart.add('MUG', 2);
  cart.add('TEE', 2);
  assert.throws(() => orders.place(cart, 'ana'), (e) => e instanceof OutOfStockError && e instanceof Error && e.sku === 'TEE');
  assert.equal(catalog.get('MUG').stock, 5);
  assert.equal(catalog.get('TEE').stock, 1);
  assert.equal(orders.list().length, 0);
  assert.equal(cart.lines().length, 2, 'the cart is kept so the customer can fix it');
});

test('cancelling an order puts the units back', () => {
  const { catalog, cart, orders } = setup();
  cart.add('MUG', 5);
  const o = orders.place(cart, 'ana');
  assert.equal(catalog.get('MUG').stock, 0);
  orders.cancel(o.id);
  assert.equal(catalog.get('MUG').stock, 5);
});
