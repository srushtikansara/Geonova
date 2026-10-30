/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        navy: { 950: '#070d19', 900: '#0a1220', 800: '#0f1b2d', 700: '#16253b', 600: '#1e2d44' },
        accent: { DEFAULT: '#22d3ee', strong: '#06b6d4', teal: '#14b8a6' },
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'Segoe UI', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Consolas', 'monospace'],
      },
    },
  },
  plugins: [],
}
