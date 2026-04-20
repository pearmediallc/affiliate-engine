/**
 * Universal vertical list — used across ALL features.
 * Single source of truth for the entire platform.
 */

export const VERTICALS = [
  { id: 'home_insurance', name: 'Home Insurance', group: 'Insurance' },
  { id: 'concealed_carry', name: 'Concealed Carry Permits', group: 'Insurance' },
  { id: 'health_insurance', name: 'Health Insurance', group: 'Insurance' },
  { id: 'life_insurance', name: 'Life Insurance', group: 'Insurance' },
  { id: 'auto_insurance', name: 'Auto Insurance', group: 'Insurance' },
  { id: 'medicare', name: 'Medicare Supplements', group: 'Insurance' },
  { id: 'nutra', name: 'Weight Loss Supplements', group: 'Health & Wellness' },
  { id: 'blood_sugar', name: 'Blood Sugar Management', group: 'Health & Wellness' },
  { id: 'cbd', name: 'CBD/Hemp Products', group: 'Health & Wellness' },
  { id: 'ed', name: 'ED Enhancement', group: 'Health & Wellness' },
  { id: 'refinance', name: 'Mortgage Refinance', group: 'Finance & Home' },
  { id: 'home_improvement', name: 'Home Improvement', group: 'Finance & Home' },
  { id: 'wifi', name: 'WiFi/Mesh Routers', group: 'Finance & Home' },
  { id: 'bizop', name: 'Work-From-Home/Bizop', group: 'Opportunity' },
] as const;

export type VerticalId = typeof VERTICALS[number]['id'];

export const VERTICAL_GROUPS = [...new Set(VERTICALS.map(v => v.group))];

export function getVerticalName(id: string): string {
  return VERTICALS.find(v => v.id === id)?.name || id;
}

/**
 * Renders a <select> dropdown with verticals grouped by category.
 * Usage: <VerticalSelect value={val} onChange={setVal} />
 */
export function verticalOptions() {
  const groups: Record<string, typeof VERTICALS[number][]> = {};
  VERTICALS.forEach(v => {
    if (!groups[v.group]) groups[v.group] = [];
    groups[v.group].push(v);
  });
  return groups;
}
