// Writes static/dist/favicon.svg, the brand sun, in the theme's primary-500, so the favicon follows the accent.
// tests/css_build/test_dist_style_css.py checks that the committed copy is what this draws.
const fs = require('fs');
const path = require('path');
const resolveConfig = require('tailwindcss/resolveConfig');

const primary = resolveConfig(require('./tailwind.config.js')).theme.colors.primary;
const accent = primary?.[500];

if (typeof accent !== 'string') {
  throw new Error(
    'The theme defines no primary-500, the colour the favicon is drawn in. '
      + "static/src/theme-tokens.json's tailwind section defines primary, "
      + `which tailwind.config.js resolves to ${JSON.stringify(primary)}.`,
  );
}

const favicon = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
  <circle cx="50" cy="50" r="20" fill="${accent}"/>
  <g stroke="${accent}" stroke-width="4" stroke-linecap="round">
    <line x1="50" y1="8" x2="50" y2="22"/>
    <line x1="50" y1="78" x2="50" y2="92"/>
    <line x1="8" y1="50" x2="22" y2="50"/>
    <line x1="78" y1="50" x2="92" y2="50"/>
    <line x1="20.3" y1="20.3" x2="30.2" y2="30.2"/>
    <line x1="69.8" y1="69.8" x2="79.7" y2="79.7"/>
    <line x1="20.3" y1="79.7" x2="30.2" y2="69.8"/>
    <line x1="69.8" y1="30.2" x2="79.7" y2="20.3"/>
  </g>
</svg>
`;

fs.writeFileSync(path.join(__dirname, 'static', 'dist', 'favicon.svg'), favicon);
