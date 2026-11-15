import { readdirSync, statSync, existsSync } from 'node:fs';
import { join } from 'node:path';

// Lists metric folders (metrics/<slug>/ that contain a metric.yml) at build time.
export function listMetricSlugs(): string[] {
  const root = join(process.cwd(), 'metrics');
  if (!existsSync(root)) return [];
  return readdirSync(root)
    .filter((name) => statSync(join(root, name)).isDirectory())
    .filter((name) => existsSync(join(root, name, 'metric.yml')))
    .sort();
}
