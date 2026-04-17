/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './app/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        apple: {
          blue: '#0071e3',
          'link': '#0066cc',
          'bright': '#2997ff',
          black: '#1d1d1f',
          'light-gray': '#f5f5f7',
          'surface-1': '#272729',
          'surface-2': '#262628',
          'surface-3': '#28282a',
          'surface-4': '#2a2a2d',
          'surface-5': '#242426',
        },
      },
      fontFamily: {
        'sf-display': ['"SF Pro Display"', '"Helvetica Neue"', 'Helvetica', 'Arial', 'sans-serif'],
        'sf-text': ['"SF Pro Text"', '"Helvetica Neue"', 'Helvetica', 'Arial', 'sans-serif'],
      },
      borderRadius: {
        'apple': '8px',
        'apple-lg': '12px',
        'pill': '980px',
      },
      boxShadow: {
        'apple': 'rgba(0, 0, 0, 0.22) 3px 5px 30px 0px',
      },
    },
  },
  plugins: [],
};
