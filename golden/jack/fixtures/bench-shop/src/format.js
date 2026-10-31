/** 12.5 -> "12.50 €" */
export function formatMoney(amount) {
  return `${amount.toFixed(2)} €`;
}
