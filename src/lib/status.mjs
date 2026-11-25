// The five status words of plan section 4 (the on-track rule). A metric that has a government target with a date
// may carry a `status` block in metric.yml; its `status` must be one of these. Used by the checker
// (scripts/validate.mjs) and the page (src/lib/metrics.ts).
export const STATUS_WORDS = ['Met', 'On track', 'Behind', 'Missed', 'Too early to say'];
