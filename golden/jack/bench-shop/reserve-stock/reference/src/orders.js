/** Thrown when an order asks for more units than are in stock. */
export class OutOfStockError extends Error {
  constructor(sku, requested, available) {
    super(`Not enough stock for ${sku}: requested ${requested}, available ${available}`);
    this.name = 'OutOfStockError';
    this.sku = sku;
  }
}

/** Turns carts into orders, reserving stock. */
export class Orders {
  #orders = new Map();
  #next = 1;

  constructor(catalog) {
    this.catalog = catalog;
  }

  place(cart, customer) {
    const summary = cart.summary();
    if (!summary.lines.length) throw new Error('Cannot place an empty order');
    for (const l of summary.lines) {
      const p = this.catalog.get(l.sku);
      if (p.stock < l.qty) throw new OutOfStockError(l.sku, l.qty, p.stock);
    }
    for (const l of summary.lines) this.catalog.get(l.sku).stock -= l.qty;
    const order = { id: this.#next++, customer, status: 'placed', ...summary };
    this.#orders.set(order.id, order);
    cart.clear();
    return order;
  }

  cancel(id) {
    const order = this.get(id);
    if (order.status !== 'placed') throw new Error(`Order ${id} is already ${order.status}`);
    for (const l of order.lines) this.catalog.get(l.sku).stock += l.qty;
    order.status = 'cancelled';
    return order;
  }

  get(id) {
    const order = this.#orders.get(id);
    if (!order) throw new Error(`Unknown order ${id}`);
    return order;
  }

  list() {
    return [...this.#orders.values()];
  }
}
