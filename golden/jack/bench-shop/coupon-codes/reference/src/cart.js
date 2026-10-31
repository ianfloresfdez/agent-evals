import { totals } from './pricing.js';

/** Percentage off the subtotal, by coupon code. */
export const COUPONS = { WELCOME10: 0.1, VIP25: 0.25 };

/** A customer's cart: SKUs and quantities, priced from the catalog. */
export class Cart {
  #items = new Map(); // sku -> qty
  #coupon = null;

  constructor(catalog) {
    this.catalog = catalog;
  }

  add(sku, qty = 1) {
    if (!Number.isInteger(qty) || qty < 1) throw new RangeError('qty must be a positive integer');
    this.catalog.get(sku); // throws for unknown products
    this.#items.set(sku, (this.#items.get(sku) ?? 0) + qty);
  }

  remove(sku) {
    this.#items.delete(sku);
  }

  applyCoupon(code) {
    const key = String(code).toUpperCase();
    if (!(key in COUPONS)) throw new Error(`Invalid coupon ${code}`);
    this.#coupon = key;
  }

  lines() {
    return [...this.#items].map(([sku, qty]) => ({ sku, qty, price: this.catalog.get(sku).price }));
  }

  summary() {
    return { lines: this.lines(), ...totals(this.lines(), this.#coupon ? COUPONS[this.#coupon] : 0) };
  }

  clear() {
    this.#items.clear();
    this.#coupon = null;
  }
}
