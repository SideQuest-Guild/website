const NUMERALS: [number, string][] = [
  [10, "X"],
  [9, "IX"],
  [5, "V"],
  [4, "IV"],
  [1, "I"],
];

/** Article numbers for the charter pages (1 → "I"). Covers 1–39, far more articles than any page has. */
export function toRoman(value: number): string {
  let rest = value;
  let out = "";
  for (const [amount, numeral] of NUMERALS) {
    while (rest >= amount) {
      out += numeral;
      rest -= amount;
    }
  }
  return out;
}
