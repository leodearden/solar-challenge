const colors = require('tailwindcss/colors');
const tokens = require('./static/src/theme-tokens.json');

/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: 'class',
  content: [
    './templates/**/*.html',
    './static/js/**/*.js',
  ],
  theme: {
    extend: {
      colors: {
        primary: colors[tokens.tailwind.primary],
      },
    },
  },
  plugins: [
    // sidebar-collapsed:<utility> applies while <html> has the sidebar-collapsed class, which base.html's head script sets before first paint.
    ({ addVariant }) => addVariant('sidebar-collapsed', '.sidebar-collapsed &'),
  ],
};
