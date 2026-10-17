/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#17201b",
        paper: "#f7f4ec",
        moss: "#60735f",
        chalk: "#e9dfc7",
        signal: "#d45d3f",
        graphite: "#2c3430"
      },
      fontFamily: {
        display: ["Georgia", "serif"],
        body: ["ui-sans-serif", "system-ui", "sans-serif"]
      },
      boxShadow: {
        panel: "0 18px 50px rgba(23, 32, 27, 0.14)"
      }
    }
  },
  plugins: []
};
