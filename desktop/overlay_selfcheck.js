// 悬浮窗改造静态自检：JS 语法 + 关键接线存在性（不启浏览器，秒级）
const fs = require('fs');
const path = require('path');
let fail = 0;
function ok(cond, name) { console.log((cond ? 'PASS ' : 'FAIL ') + name); if (!cond) fail++; }

// 1) recorder.js / main.js / preload.js 语法
for (const f of ['../server/static/js/recorder.js', 'main.js', 'preload.js']) {
  const p = path.join(__dirname, f);
  try { new Function(fs.readFileSync(p, 'utf8')); ok(true, 'syntax ' + f); }
  catch (e) { ok(false, 'syntax ' + f + ' :: ' + e.message); }
}

// 2) overlay.html 主内联脚本语法（取最后一个 <script> 块）
const html = fs.readFileSync(path.join(__dirname, '../server/templates/overlay.html'), 'utf8');
const blocks = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
ok(blocks.length >= 1, 'overlay inline script found');
try { new Function(blocks[blocks.length - 1]); ok(true, 'syntax overlay inline'); }
catch (e) { ok(false, 'syntax overlay inline :: ' + e.message); }

// 3) 关键接线
ok(/armGestureRecap\(\)\s*{/.test(html) && /armGestureRecap\(\);/.test(html), 'recapture gesture fallback wired');
ok(/restartLoopAudio\('点击恢复采集', true\)/.test(html), '手势重试 force 绕去抖（页面侧）');
ok(/runSummary\(\)\)\.catch\(\(\) => \{\}\)\.then/.test(html), '总结链式调度 catch 不断链');
ok(!/state\.sumTimer/.test(html), '旧 sumTimer 已全清');
ok(!/llOverlayDrag/.test(html), '旧 JS 拖拽已从页面移除');
ok(/-webkit-app-region:drag/.test(html) && /-webkit-app-region:no-drag/.test(html), '原生拖拽 CSS 就位');
ok(/value="300"/.test(html), '间隔默认 300s');
ok(/vendor\/marked\.min\.js/.test(html) && /vendor\/purify\.min\.js/.test(html) && /md_render\.js/.test(html), 'MD 渲染链脚本引入');
ok(/setTransform\(dpr/.test(html), '波形每帧 setTransform');
ok(/rec\.seconds\(\)/.test(html), '计时读公开 getter');
// A4 顺序守卫：applyMath 必须在 wrap 挂进文档之后调用（isConnected 守卫跳过分离节点，占位符残留回归防线）
const asv = (html.match(/function appendSummaryView[\s\S]*?\n  \}/) || [''])[0];
ok(/el\.appendChild\(wrap\)[\s\S]*applyMath/.test(asv), 'appendSummaryView 先挂载后 applyMath');
ok(/llOverlayResize/.test(html) && /llOverlayResize/.test(fs.readFileSync(path.join(__dirname, 'preload.js'), 'utf8')), 'resize 桥两端接线');

// 4) recorder 引擎守护
const rec = fs.readFileSync(path.join(__dirname, '../server/static/js/recorder.js'), 'utf8');
ok(/restartLoopAudio/.test(rec) && /_ensureLoopWatch/.test(rec) && /devicechange/.test(rec), 'loopback 自愈守护就位');
ok(/_deviceChangeBound/.test(rec) && !/addEventListener\('devicechange', function/.test(rec), 'devicechange 监听单次注册（防累积泄漏）');
ok(/\(reason, force\)/.test(rec) && /!force && now - this\._lastRecapTs/.test(rec), '手势路径 force 绕过去抖');
ok(/_restartInFlight/.test(rec) && /finally \{\s*\n?\s*this\._restartInFlight = false/.test(rec.replace(/\r?\n/g, '\n')), 'restart 串行化屏障含 finally 释放');
ok(/_lastRecapTs = now;[\s\S]*getDisplayMedia[\s\S]*state === 'idle'[\s\S]*t\.stop\(\)/.test(rec), '重取 await 后状态复检防孤儿活流');
ok(/seconds = function/.test(rec), 'seconds getter');
const mainjs = fs.readFileSync(path.join(__dirname, 'main.js'), 'utf8');
ok(/backgroundThrottling: false/.test(mainjs), 'overlay 关后台节流');
ok(/overlay:resize/.test(mainjs) && !/ipcMain\.on\('overlay:drag'/.test(mainjs), '主进程 drag→resize 切换');
ok(/setDisplayMediaRequestHandler/.test(mainjs), '免弹框共享 handler 仍在');

console.log(fail ? 'SELF_CHECK_FAIL ' + fail : 'SELF_CHECK_ALL_PASS');
process.exit(fail ? 1 : 0);
