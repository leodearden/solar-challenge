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
        // Copies Tailwind's built-in amber: tests/unit/test_web_theme_colours.py relies on that.
        primary: {
          50: '#fffbeb',
          100: '#fef3c7',
          200: '#fde68a',
          300: '#fcd34d',
          400: '#fbbf24',
          500: '#f59e0b',
          600: '#d97706',
          700: '#b45309',
          800: '#92400e',
          900: '#78350f',
        },
      },
    },
  },
  plugins: [
    // sidebar-collapsed:<utility> applies while <html> has the sidebar-collapsed class, which base.html's head script sets before first paint.
    ({ addVariant }) => addVariant('sidebar-collapsed', '.sidebar-collapsed &'),
  ],
};
