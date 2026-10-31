/** 1234.5 -> "1,234.50 €" */
export function formatMoney(amount) {
  const [int, dec] = Math.abs(amount).toFixed(2).split('.');
  const grouped = int.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return `${amount < 0 ? '-' : ''}${grouped}.${dec} €`;
}
