/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ui: {
          bg: '#ffffff',
          surface: '#ffffff',
          soft: '#f5f5f7',
          text: '#1d1d1f',
          muted: '#6e6e73',
          line: '#d2d2d7',
          accent: '#0066cc',
        },
        dark: {
          bg: '#000000',
          surface: '#1d1d1f',
          soft: '#2c2c2e',
          text: '#f5f5f7',
          muted: '#a1a1a6',
          line: '#38383a',
          accent: '#2997ff',
        },
      },
      borderRadius: {
        sm2: '8px',
        md2: '12px',
        lg2: '16px',
      },
      fontFamily: {
        system: ['-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'sans-serif'],
        pretendard: ['Pretendard Variable', 'Pretendard', 'sans-serif'],
        noto: ['Noto Sans KR', 'sans-serif'],
        githubnoto: ['GithubNoto', 'Noto Sans KR', 'sans-serif'],
        school: ['SchoolSafeUniverse', 'sans-serif'],
        inter: ['Inter', 'sans-serif'],
      },
    },
  },
  plugins: [],
};
