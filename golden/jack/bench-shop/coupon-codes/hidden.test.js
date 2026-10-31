import { test } from 'node:test';
import assert from 'node:assert/strict';
import { Catalog, Cart, COUPONS } from '../src/index.js';

function cart() {
  const c = new Catalog();
  c.add({ sku: 'TEE', name: 'T-shirt', price: 20, stock: 10 });
  const cart = new Cart(c);
  cart.add('TEE', 2); // subtotal 40
  return cart;
}

test('coupon table is exported', () => {
  assert.equal(COUPONS.WELCOME10, 0.1);
  assert.equal(COUPONS.VIP25, 0.25);
});

test('a valid coupon discounts the subtotal before tax', () => {
  const c = cart();
  c.applyCoupon('WELCOME10');
  const s = c.summary();
  assert.equal(s.subtotal, 40);
  assert.equal(s.discount, 4);
  assert.equal(s.tax, 7.56);
  assert.equal(s.total, 43.56);
});

test('codes are case-insensitive and a second coupon replaces the first', () => {
  const c = cart();
  c.applyCoupon('welcome10');
  c.applyCoupon('vip25');
  const s = c.summary();
  assert.equal(s.discount, 10);
  assert.equal(s.total, 36.3);
});

test('unknown codes throw and leave the cart unchanged', () => {
  const c = cart();
  assert.throws(() => c.applyCoupon('NOPE'), /Invalid coupon/);
  const s = c.summary();
  assert.equal(s.discount, 0);
  assert.equal(s.total, 48.4);
});
