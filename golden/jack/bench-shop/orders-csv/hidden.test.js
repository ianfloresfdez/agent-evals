import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ordersToCsv } from '../src/index.js';

const order = (id, customer, status, total) => ({ id, customer, status, total, lines: [], subtotal: total, tax: 0 });

test('header and one row per order, totals with two decimals', () => {
  const csv = ordersToCsv([order(1, 'ana', 'placed', 9.68), order(2, 'bob', 'cancelled', 24.2)]);
  assert.equal(csv, 'id,customer,status,total\n1,ana,placed,9.68\n2,bob,cancelled,24.20');
});

test('no orders gives just the header', () => {
  assert.equal(ordersToCsv([]), 'id,customer,status,total');
});

test('fields with commas, quotes or newlines are quoted and inner quotes doubled', () => {
  const csv = ordersToCsv([order(3, 'Smith, "Bo"', 'placed', 1), order(4, 'line\nbreak', 'placed', 2)]);
  assert.equal(csv, 'id,customer,status,total\n3,"Smith, ""Bo""",placed,1.00\n4,"line\nbreak",placed,2.00');
});
