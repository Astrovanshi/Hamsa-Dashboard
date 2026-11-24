/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        radar: {
          bg: '#07090e',
          card: '#0d1117',
          cardHover: '#131822',
          border: '#1b2230',
          borderLight: '#242e42',
          muted: '#526079',
          text: '#c9d1d9',
          textBright: '#f0f6fc',
          accent: '#1f6feb',
          accentGlow: 'rgba(31, 111, 235, 0.15)',
          gold: '#d29922',
          cyan: '#38bdf8',
          emerald: '#238636',
          emeraldGlow: 'rgba(35, 134, 54, 0.15)',
          crimson: '#da3633',
          crimsonGlow: 'rgba(218, 54, 51, 0.15)',
          purple: '#8957e5',
        }
      },
      fontFamily: {
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'Monaco', 'Consolas', 'monospace'],
        sans: ['-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', 'Roboto', 'Helvetica', 'Arial', 'sans-serif'],
      }
    },
  },
  plugins: [],
}