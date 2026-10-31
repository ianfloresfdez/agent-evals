import { Catalog } from '../src/index.js';

export function shop() {
  const catalog = new Catalog();
  catalog.add({ sku: 'MUG', name: 'Mug', price: 8, stock: 50 });
  catalog.add({ sku: 'TEE', name: 'T-shirt', price: 20, stock: 5 });
  catalog.add({ sku: 'CAP', name: 'Cap', price: 12.5, stock: 0 });
  return catalog;
}
