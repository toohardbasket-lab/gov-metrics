import { defineConfig } from 'astro/config';
import config from './site.config.mjs';

export default defineConfig({
  output: 'static',
  site: config.baseUrl || undefined,
});
