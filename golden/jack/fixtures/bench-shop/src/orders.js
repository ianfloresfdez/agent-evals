/** Turns carts into orders. */
export class Orders {
  #orders = new Map();
  #next = 1;

  constructor(catalog) {
    this.catalog = catalog;
  }

  place(cart, customer) {
    const summary = cart.summary();
    if (!summary.lines.length) throw new Error('Cannot place an empty order');
    const order = { id: this.#next++, customer, status: 'placed', ...summary };
    this.#orders.set(order.id, order);
    cart.clear();
    return order;
  }

  cancel(id) {
    const order = this.get(id);
    if (order.status !== 'placed') throw new Error(`Order ${id} is already ${order.status}`);
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
