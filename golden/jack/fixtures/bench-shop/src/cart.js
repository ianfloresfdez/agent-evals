import { totals } from './pricing.js';

/** A customer's cart: SKUs and quantities, priced from the catalog. */
export class Cart {
  #items = new Map(); // sku -> qty

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

  lines() {
    return [...this.#items].map(([sku, qty]) => ({ sku, qty, price: this.catalog.get(sku).price }));
  }

  summary() {
    return { lines: this.lines(), ...totals(this.lines()) };
  }

  clear() {
    this.#items.clear();
  }
}
