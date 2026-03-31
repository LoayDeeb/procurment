/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./index.html",
    "./src/**/*.{js,jsx,ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        sidebar: '#18213A',
        primary: '#F4F6FA',
        card: '#fff',
        accent: '#E7EAF3',
        button: '#F7F8FA',
        icon: '#6B7280',
      },
      fontFamily: {
        sans: ['Inter', 'sans-serif'],
      },
    },
  },
  plugins: [],
};
