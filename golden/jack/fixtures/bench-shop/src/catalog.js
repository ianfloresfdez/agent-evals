/** Products and how many units are in stock. */
export class Catalog {
  #products = new Map();

  add({ sku, name, price, stock = 0 }) {
    if (!sku || !name) throw new TypeError('sku and name are required');
    if (!(price >= 0)) throw new RangeError('price must be >= 0');
    if (this.#products.has(sku)) throw new Error(`Product ${sku} already exists`);
    const product = { sku, name, price, stock };
    this.#products.set(sku, product);
    return product;
  }

  get(sku) {
    const p = this.#products.get(sku);
    if (!p) throw new Error(`Unknown product ${sku}`);
    return p;
  }

  all() {
    return [...this.#products.values()];
  }
}
