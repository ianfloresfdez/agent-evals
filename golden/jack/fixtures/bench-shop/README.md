# bench-shop

A small online-shop domain: products and stock, a cart with discounts and tax, orders, and money
formatting. Plain ES modules, no dependencies; `npm test` runs Node's test runner.

- `src/catalog.js`   products and stock levels
- `src/pricing.js`   line totals, bulk discount, tax
- `src/cart.js`      a customer's cart and its summary
- `src/orders.js`    placing and cancelling orders
- `src/format.js`    money formatting
- `src/index.js`     public API (everything a caller may import)
