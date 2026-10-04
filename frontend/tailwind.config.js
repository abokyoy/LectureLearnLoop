/**
 * 柯基学习乐园 Tailwind 预编译配置
 * - 旧 token（primary/text-gray 等）原样保留，供未迁移页面兼容；批8收尾时统一清理
 * - 新设计系统 token 一律 cl-* 前缀，值与 design/DESIGN.md 对齐（唯一契约）
 */
const colors = require('tailwindcss/colors');

module.exports = {
  darkMode: 'class',
  content: [
    '../server/templates/**/*.html',
    '../server/static/js/**/*.js',
  ],
  safelist: [
    // 内联 JS 动态切换的类，防抖漏
    { pattern: /^(hidden|w-64|w-16|text-white|bg-primary|collapsed|active)$/ },
    // 批3：JS classList 动态切换的新设计系统类（仅出现在脚本字符串中）
    'bg-cl-surface', 'text-cl-primary', 'shadow-cl', 'text-cl-text-2',
    'bg-cl-warning', 'hover:bg-cl-warning\/90', 'bg-cl-danger', 'hover:bg-cl-danger\/90',
    'bg-cl-text-2', 'hover:bg-cl-text',
  ],
  theme: {
    extend: {
      colors: {
        // ===== 旧 token（兼容未迁移页面，勿新增使用）=====
        primary: '#32C77F',
        warning: '#FF9B27',
        danger: '#ED4B4B',
        'text-dark-brown': '#715D46',
        'text-medium-brown': '#9B8D7D',
        'text-gray': '#828282',
        'bg-light-blue': '#D5F8FF',
        'bg-beige': '#FFFFD6',
        'bg-light-green': '#E2F2EB',
        'bg-light-gray': '#F2F0ED',
        'bg-light-blue-gray': '#F5F7F9',
        // ===== 新设计系统 token（DESIGN.md §2）=====
        cl: {
          primary: '#F97316',
          'primary-hover': '#EA6C0B',
          'primary-soft': '#FFF1E7',
          secondary: '#10B981',
          'secondary-soft': '#E7F8F1',
          bg: '#FAF7F2',
          surface: '#FFFFFF',
          border: '#EFE9E0',
          text: '#292524',
          'text-2': '#78716C',
          'text-3': '#A8A29E',
          danger: '#EF4444',
          warning: '#F59E0B',
        },
      },
      fontFamily: {
        cl: ['system-ui', '"PingFang SC"', '"Microsoft YaHei"', 'sans-serif'],
        sans: ['"Noto Sans SC"', 'sans-serif'],
      },
      borderRadius: {
        xl: '1rem',
        cl: '12px',
        clbtn: '10px',
      },
      boxShadow: {
        cl: '0 1px 2px rgba(41,37,36,0.04)',
        'cl-hover': '0 6px 16px rgba(41,37,36,0.08)',
      },
    },
  },
  plugins: [require('@tailwindcss/forms'), require('@tailwindcss/typography')],
};
