const cell = (v) => {
  const s = String(v);
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
};

/** CSV export of orders: header plus one row per order, rows separated by \n, no trailing newline. */
export function ordersToCsv(orders) {
  const rows = orders.map((o) => [o.id, o.customer, o.status, o.total.toFixed(2)].map(cell).join(','));
  return ['id,customer,status,total', ...rows].join('\n');
}
