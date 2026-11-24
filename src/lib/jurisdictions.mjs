// The fixed order and short names for the state and territory panel (plan section 3):
// NSW, Vic, Qld, WA, SA, Tas, ACT, NT. Used by the checker (scripts/validate.mjs) and the page
// (src/lib/metrics.ts). The names are the full names written in the jurisdiction column of data.csv.
export const STATE_ORDER = [
  { jurisdiction: 'New South Wales', abbreviation: 'NSW' },
  { jurisdiction: 'Victoria', abbreviation: 'Vic' },
  { jurisdiction: 'Queensland', abbreviation: 'Qld' },
  { jurisdiction: 'Western Australia', abbreviation: 'WA' },
  { jurisdiction: 'South Australia', abbreviation: 'SA' },
  { jurisdiction: 'Tasmania', abbreviation: 'Tas' },
  { jurisdiction: 'Australian Capital Territory', abbreviation: 'ACT' },
  { jurisdiction: 'Northern Territory', abbreviation: 'NT' },
];
