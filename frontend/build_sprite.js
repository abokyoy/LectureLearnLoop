/**
 * 从 lucide-static 生成 SVG sprite -> ../server/static/icons/lucide-sprite.svg
 * 用法: node build_sprite.js
 * 新增图标时把名字加进 ICONS 数组并重跑 npm run build:sprite
 */
const fs = require('fs');
const path = require('path');

const ICONS = [
  // 壳层（批1）
  'layout-dashboard', 'graduation-cap', 'dumbbell', 'brain', 'library', 'settings',
  'user', 'chevron-left', 'chevron-right', 'headphones', 'log-out', 'dog',
  // 工作台及后续批次预置
  'sparkles', 'clock', 'flame', 'book-open', 'pen-line', 'target', 'lightbulb',
  'history', 'alert-circle', 'file-text', 'mic', 'camera', 'download', 'x', 'check',
  'check-circle-2', 'arrow-right', 'search', 'plus', 'trash-2', 'refresh-cw',
  'chart-column', 'list-tree', 'wallet', 'coins', 'scroll-text', 'notebook-pen',
  'book-marked', 'layers', 'bell', 'calendar-days',
  // 批3 网课笔记页
  'folder-plus', 'file-plus', 'eye', 'save', 'circle', 'square', 'panel-left-close', 'folder-open', 'sparkle',
];

const SRC_DIR = path.join(__dirname, 'node_modules', 'lucide-static', 'icons');
const OUT = path.join(__dirname, '..', 'server', 'static', 'icons', 'lucide-sprite.svg');

let missing = [];
const symbols = [];
for (const name of ICONS) {
  const f = path.join(SRC_DIR, name + '.svg');
  if (!fs.existsSync(f)) { missing.push(name); continue; }
  let svg = fs.readFileSync(f, 'utf8');
  // 提取 <svg> 内部内容，去掉根属性，统一 stroke 参数
  const inner = svg.replace(/^[\s\S]*?<svg[^>]*>/, '').replace(/<\/svg>\s*$/, '');
  symbols.push(`  <symbol id="li-${name}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">${inner}</symbol>`);
}
if (missing.length) {
  console.error('MISSING icons:', missing.join(', '));
  process.exit(1);
}
fs.mkdirSync(path.dirname(OUT), { recursive: true });
fs.writeFileSync(OUT, `<svg xmlns="http://www.w3.org/2000/svg" style="display:none">\n${symbols.join('\n')}\n</svg>\n`, 'utf8');
console.log('sprite written:', OUT, symbols.length, 'icons');
