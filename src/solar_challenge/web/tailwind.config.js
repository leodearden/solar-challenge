const colors = require('tailwindcss/colors');
const tokens = require('./static/src/theme-tokens.json');

// The palette of shades Tailwind itself defines as name; any other value fails the build, naming the role.
function builtIn(role, name) {
  const palette = typeof name === 'string' && Object.hasOwn(colors, name) ? colors[name] : undefined;
  if (typeof palette !== 'object') {
    throw new Error(
      `static/src/theme-tokens.json: tailwind.${role} names ${JSON.stringify(name)}, which is no built-in Tailwind palette`,
    );
  }
  return palette;
}

// Each role's key path and palette, in section order; an object value is a group, whose roles' paths start with its key.
function roles(section, group) {
  return Object.entries(section).flatMap(([key, value]) => {
    const path = [...group, key];
    const isGroup = typeof value === 'object' && value !== null && !Array.isArray(value);
    return isGroup ? roles(value, path) : [[path, builtIn(path.join('.'), value)]];
  });
}

// Each role's palette under the name its classes write, its path joined by hyphens (bg-status-running-100); two roles of one name fail the build.
function palettesByName(section) {
  const paths = new Map();
  const palettes = new Map();
  for (const [path, palette] of roles(section, [])) {
    const name = path.join('-');
    if (paths.has(name)) {
      throw new Error(
        `static/src/theme-tokens.json: tailwind.${paths.get(name)} and tailwind.${path.join('.')} both define the Tailwind colour ${name}, so one of their palettes would silently replace the other`,
      );
    }
    paths.set(name, path.join('.'));
    palettes.set(name, palette);
  }
  return Object.fromEntries(palettes);
}

/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: 'class',
  content: [
    './templates/**/*.html',
    './static/js/**/*.js',
  ],
  theme: {
    extend: {
      colors: palettesByName(tokens.tailwind),
    },
  },
  plugins: [
    // sidebar-collapsed:<utility> applies while <html> has the sidebar-collapsed class, which base.html's head script sets before first paint.
    ({ addVariant }) => addVariant('sidebar-collapsed', '.sidebar-collapsed &'),
  ],
};
