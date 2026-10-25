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

// Each role's palette by key; an object value is a group, whose roles Tailwind names like bg-status-running-100.
function roles(section, group) {
  return Object.fromEntries(
    Object.entries(section).map(([key, value]) => {
      const role = group ? `${group}.${key}` : key;
      const isGroup = typeof value === 'object' && value !== null && !Array.isArray(value);
      return [key, isGroup ? roles(value, role) : builtIn(role, value)];
    }),
  );
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
      colors: roles(tokens.tailwind, ''),
    },
  },
  plugins: [
    // sidebar-collapsed:<utility> applies while <html> has the sidebar-collapsed class, which base.html's head script sets before first paint.
    ({ addVariant }) => addVariant('sidebar-collapsed', '.sidebar-collapsed &'),
  ],
};
