export const TAX_RATE = 0.21;
export const BULK_MIN_QTY = 10;
export const BULK_DISCOUNT = 0.1;

const round2 = (n) => Math.round(n * 100) / 100;

/** Price of one cart line; lines of BULK_MIN_QTY units or more get the bulk discount. */
export function lineTotal(price, qty) {
  const gross = price * qty;
  return round2(qty > BULK_MIN_QTY ? gross * (1 - BULK_DISCOUNT) : gross);
}

/** Subtotal, tax and total for a list of { price, qty } lines. */
export function totals(lines) {
  const subtotal = round2(lines.reduce((s, l) => s + lineTotal(l.price, l.qty), 0));
  const tax = round2(subtotal * TAX_RATE);
  return { subtotal, tax, total: round2(subtotal + tax) };
}
