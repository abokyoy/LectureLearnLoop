/**
 * LectureLearnLoop Electron 主进程。
 *
 * P2：主窗口加载 Flask 服务端页面。
 * P4：悬浮录音窗（/overlay）、Deepgram 流式 WS 代理（asr_proxy）、框选截屏。
 */
const { app, BrowserWindow, ipcMain, session, desktopCapturer, screen, Menu } = require('electron');
const path = require('path');
const fs = require('fs');
const asr = require('./asr_proxy');

// 服务器地址：环境变量 > 随附 server_url.txt（与 main.js 同目录或 resources 下，打包时写入）> 本地默认 127.0.0.1:9992
// 不依赖 app.isPackaged（win-unpacked 目录注入方式下其判定不可靠），直接按文件存在性解析
function readServerUrlFile() {
  var cands = [path.join(__dirname, 'server_url.txt')];
  try { cands.push(path.join(process.resourcesPath, 'server_url.txt')); } catch (e) {}
  for (var i = 0; i < cands.length; i++) {
    try { if (fs.existsSync(cands[i])) return fs.readFileSync(cands[i], 'utf8').trim(); } catch (e) {}
  }
  return '';
}
const SERVER_BASE = process.env.LL_SERVER || readServerUrlFile() || 'http://127.0.0.1:9992';

// 客户版连接的是 http://域名:端口（非安全上下文），Chromium 会把 navigator.mediaDevices 置为
// undefined → 悬浮窗录音报 "Cannot read properties of undefined (reading 'getDisplayMedia')"；
// 开发机用 127.0.0.1（回环天然安全）故从不复现。这里把当前服务地址明确视为安全上下文。
// 必须在 app ready 前追加；回环/https 地址下不追加。用 URL().origin 归一化：
// Chromium 要求开关值是纯 origin（带尾斜杠/路径会被静默忽略，导致修复失效）；
// 客户手改 server_url.txt 时从地址栏粘贴常带 "/"，此处兜住。
if (/^http:\/\//i.test(SERVER_BASE)) {
  try {
    const _u = new URL(SERVER_BASE);
    const _isLoopback = ['localhost', '127.0.0.1', '[::1]', '::1'].includes(_u.hostname);
    if (!_isLoopback) {
      app.commandLine.appendSwitch('unsafely-treat-insecure-origin-as-secure', _u.origin);
    }
  } catch (e) { /* 地址畸形：不追加开关，后续 loadURL 会走 did-fail-load 提示链路 */ }
}

let mainWindow = null;
let overlayWindow = null;
let overlayGeom = null; // 会话内记住悬浮窗 bounds（尺寸/位置），重开不丢
let captureWindow = null;
let serverDownRetries = 0;
let asrSession = null; // {send, close}

function loadServerPage(win) {
  win.loadURL(SERVER_BASE + '/').catch(() => { /* did-fail-load 里统一处理 */ });
}

function createMainWindow() {
  const isMac = process.platform === 'darwin';
  mainWindow = new BrowserWindow({
    width: 1360,
    height: 860,
    title: '柯基学习小助手',
    autoHideMenuBar: true, // 不展示原生菜单栏（菜单本体已在 whenReady 里置 null）
    backgroundColor: '#FAF7F2',
    // 一体化头部：去掉 Windows 原生标题栏，页面顶栏即为窗口头。
    // Windows：hidden + titleBarOverlay，原生最小化/最大化/关闭按钮用顶栏同色融合（产品规则：页面内不自绘窗口按钮）；
    // macOS：hidden + 自定义位置红绿灯，CSS 侧让侧边栏logo下移避让。
    titleBarStyle: 'hidden',
    ...(isMac
      ? { trafficLightPosition: { x: 18, y: 16 } }
      : { titleBarOverlay: { color: '#FFFFFF', symbolColor: '#78716C', height: 56 } }),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  mainWindow.webContents.on('did-fail-load', (e, errorCode, errorText, failedUrl) => {
    if (errorCode === -3 /* ABORTED */ || !String(failedUrl).startsWith(SERVER_BASE)) return;
    if (serverDownRetries < 30) {
      serverDownRetries += 1;
      setTimeout(() => { if (mainWindow && !mainWindow.isDestroyed()) loadServerPage(mainWindow); }, 2000);
    } else {
      mainWindow.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(
        '<h2 style="font-family:sans-serif">⚠️ 无法连接服务器 ' + SERVER_BASE + '</h2>' +
        '<p style="font-family:sans-serif">请检查本机网络后重新打开本应用；若仍无法连接，请联系管理员确认服务是否在线。</p>'));
    }
  });
  mainWindow.webContents.on('did-finish-load', () => { serverDownRetries = 0; });

  loadServerPage(mainWindow);
  mainWindow.on('closed', () => { mainWindow = null; });
}

/* ------------------------------------------------------- 登录态跨窗口同步 */
// 登录未勾选“记住登录”时 token 只存在主窗口 sessionStorage，而子窗口（悬浮窗/笔记选择窗）
// 是独立 BrowserWindow，sessionStorage 不跨窗口共享 → 子窗口会误报“未登录”。
// 方案：主进程提供 auth:getToken 按需拉取（与 app:getServerBase 同口径），子窗口在关键操作前
// 经 preload 的 llAuth.refresh() 实时读主窗口 token；避免 argv 快照的旧 token 滞留/登出不生效问题。
async function getMainAuthToken() {
  if (!mainWindow || mainWindow.isDestroyed()) return '';
  const js = "(window.llGetToken ? window.llGetToken() : (localStorage.getItem('ll_token') || sessionStorage.getItem('ll_token') || '')) || ''";
  try {
    // executeJavaScript 在主窗口页面未加载完时会排队，加 2s 兜底超时防挂起
    return await Promise.race([
      mainWindow.webContents.executeJavaScript(js),
      new Promise((res) => setTimeout(() => res(''), 2000)),
    ]) || '';
  } catch (e) { return ''; }
}

ipcMain.handle('auth:getToken', async () => getMainAuthToken());

/* ------------------------------------------------------- 悬浮录音窗（P4） */

function createOverlayWindow() {
  if (overlayWindow && !overlayWindow.isDestroyed()) {
    overlayWindow.show();
    return;
  }
  const wa = screen.getPrimaryDisplay().workArea;
  // 会话内记住尺寸/位置（用户手动 resize 后重开不丢）；首开默认右上角
  const geom = overlayGeom || {
    x: wa.x + wa.width - 380,
    y: wa.y + 40,
    width: 360,
    height: 560,
  };
  overlayWindow = new BrowserWindow({
    width: geom.width,
    height: geom.height,
    x: geom.x,
    y: geom.y,
    frame: false,
    alwaysOnTop: true,
    resizable: false,
    skipTaskbar: true,
    transparent: false,
    title: '学习悬浮窗',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      // 电平声波动画靠 requestAnimationFrame：悬浮窗常态是“未聚焦”小窗，
      // 默认后台节流会把 RAF/定时器压到几乎停走（现象：电平图只在拖拽窗口时才动）。
      // 与主窗口同口径显式关闭（本窗业务：计时/倒计时/电平/总结轮询全部需要持续运行）。
      backgroundThrottling: false,
    },
  });
  overlayWindow.setAlwaysOnTop(true, 'screen-saver');
  overlayWindow.loadURL(SERVER_BASE + '/overlay');
  const rememberGeom = () => {
    if (overlayWindow && !overlayWindow.isDestroyed()) overlayGeom = overlayWindow.getBounds();
  };
  // 事件名用 'move'/'resize'（Windows 下 'moved'/'resized' 是 macOS 专属，不会触发）
  overlayWindow.on('move', rememberGeom);
  overlayWindow.on('resize', rememberGeom);
  overlayWindow.on('closed', () => { overlayWindow = null; });
}

ipcMain.handle('overlay:open', () => { createOverlayWindow(); return true; });
// 关闭 = 彻底销毁窗口（destroy）：之前仅 hide() 会留下隐藏的空窗口，
// 叠加渲染层把 body 设为 display:none 的旧逻辑，导致“黑浮层常驻、再点无反应”。
ipcMain.handle('overlay:close', () => {
  if (overlayWindow && !overlayWindow.isDestroyed()) overlayWindow.destroy();
  overlayWindow = null;
  return true;
});
ipcMain.handle('overlay:hide', () => {
  if (overlayWindow && !overlayWindow.isDestroyed()) overlayWindow.destroy();
  overlayWindow = null;
  return true;
});
// 悬浮窗尺寸调整（渲染层右下角把手驱动）：frameless 窗口系统无可见边框，
// 由页面自绘把手发目标宽高，主进程钳范后 setContentSize。
// 旧 'overlay:drag'（逐 mousemove setPosition）已删：拖拽改走 CSS app-region 原生拖，
// 高频 IPC+SetWindowPos 在 Windows/DWM 下会产生被拉宽的拖影（用户报“越拖越宽”）。
const OVERLAY_SIZE_MIN = { w: 320, h: 420 };
const OVERLAY_SIZE_MAX = { w: 960, h: 1280 };
ipcMain.on('overlay:resize', (e, w, h) => {
  if (!overlayWindow || overlayWindow.isDestroyed()) return;
  // 只接受数字入参（渲染层可信但仍防御 NaN/字符串）
  const cw = Math.round(Number(w)), chh = Math.round(Number(h));
  if (!Number.isFinite(cw) || !Number.isFinite(chh)) return;
  const clampedW = Math.min(OVERLAY_SIZE_MAX.w, Math.max(OVERLAY_SIZE_MIN.w, cw));
  const clampedH = Math.min(OVERLAY_SIZE_MAX.h, Math.max(OVERLAY_SIZE_MIN.h, chh));
  overlayWindow.setContentSize(clampedW, clampedH);
});

/* ------------------------------------------------------- ASR 会话（P4） */

ipcMain.handle('asr:start', (e, cfg) => {
  if (asrSession) { try { asrSession.close(); } catch (err) {} }
  const target = e.sender;
  asrSession = asr.startSession(cfg, (ev) => {
    if (!target.isDestroyed()) target.send('asr:result', ev);
  });
  return { started: true };
});

ipcMain.on('asr:chunk', (e, arrayBuffer) => {
  if (!asrSession) return;
  // ArrayBuffer → Buffer（无此转换 ws 会发 [object ArrayBuffer] 报错）
  asrSession.send(Buffer.from(arrayBuffer));
});

ipcMain.handle('asr:stop', () => {
  if (asrSession) { asrSession.close(); asrSession = null; }
  return { stopped: true };
});

/* ------------------------------------------------------- 截屏（P4） */

async function grabScreen() {
  const displays = screen.getAllDisplays();
  const primary = displays[0];
  const size = primary.size;
  const dpr = primary.scaleFactor || 1;
  const sources = await desktopCapturer.getSources({
    types: ['screen'],
    thumbnailSize: { width: Math.round(size.width * dpr), height: Math.round(size.height * dpr) },
  });
  if (!sources.length) return null;
  return {
    dataUrl: sources[0].thumbnail.toDataURL(),
    width: size.width,   // CSS 像素（供框选坐标）
    height: size.height,
    physWidth: Math.round(size.width * dpr), // 物理像素（供裁切）
    physHeight: Math.round(size.height * dpr),
  };
}

ipcMain.handle('capture:getScreen', async () => grabScreen());

ipcMain.handle('capture:fullScreen', async () => {
  const s = await grabScreen();
  if (!s) return null;
  return { dataUrl: s.dataUrl, width: s.width, height: s.height,
           rect: { x: 0, y: 0, width: s.width, height: s.height },
           physWidth: s.physWidth, physHeight: s.physHeight };
});

// 框选窗口完成选择后由 captureWindow 通过 IPC 回传，主进程转交调用方（悬浮窗）
let pendingRegionResolver = null;

ipcMain.handle('capture:selectRegion', async (e) => {
  const s = await grabScreen();
  if (!s) return null;
  if (overlayWindow && !overlayWindow.isDestroyed()) overlayWindow.hide();
  return new Promise((resolve) => {
    pendingRegionResolver = (rect) => resolve(rect ? Object.assign({ rect }, s) : null);
    captureWindow = new BrowserWindow({
      width: s.width,
      height: s.height,
      x: 0, y: 0,
      frame: false,
      fullscreen: true,
      transparent: false,
      alwaysOnTop: true,
      skipTaskbar: true,
      webPreferences: {
        preload: path.join(__dirname, 'preload.js'),
        contextIsolation: true,
        nodeIntegration: false,
      },
    });
    captureWindow.setAlwaysOnTop(true, 'screen-saver');
    captureWindow.loadURL(SERVER_BASE + '/capture');
    captureWindow.webContents.once('did-finish-load', () => {
      captureWindow.webContents.send('capture:image', s);
    });
    captureWindow.on('closed', () => {
      captureWindow = null;
      if (overlayWindow && !overlayWindow.isDestroyed()) overlayWindow.show();
      if (pendingRegionResolver) { pendingRegionResolver(null); pendingRegionResolver = null; }
    });
  });
});

ipcMain.on('capture:region-selected', (e, rect) => {
  // rect: {x,y,width,height} CSS 像素；附带截图尺寸由渲染层回传完整信息
  if (captureWindow && !captureWindow.isDestroyed()) captureWindow.close();
  if (pendingRegionResolver) { pendingRegionResolver(rect || null); pendingRegionResolver = null; }
});

/* ------------------------------------------------------- 笔记选择窗（二期） */
// 仿 capture:selectRegion 的 Promise 模式：invoke('notepicker:open') 挂起，
// 选择页通过 notepicker:choose 回传 {action:'open'|'new', path, name} 或 null（取消）。
let notePickerWindow = null;
let pendingPickerResolver = null;

ipcMain.handle('notepicker:open', async (e) => {
  const callerIsOverlay = overlayWindow && !overlayWindow.isDestroyed()
    && e.sender === overlayWindow.webContents;
  if (callerIsOverlay) overlayWindow.hide();
  return new Promise((resolve) => {
    pendingPickerResolver = (sel) => resolve(sel || null);
    notePickerWindow = new BrowserWindow({
      width: 460,
      height: 600,
      title: '选择学习笔记',
      autoHideMenuBar: true,
      alwaysOnTop: true,
      parent: (mainWindow && !mainWindow.isDestroyed()) ? mainWindow : undefined,
      modal: !!(mainWindow && !mainWindow.isDestroyed()) && !callerIsOverlay,
      webPreferences: {
        preload: path.join(__dirname, 'preload.js'),
        contextIsolation: true,
        nodeIntegration: false,
      },
    });
    notePickerWindow.setAlwaysOnTop(true, 'screen-saver');
    notePickerWindow.loadURL(SERVER_BASE + '/note-picker');
    notePickerWindow.on('closed', () => {
      notePickerWindow = null;
      if (callerIsOverlay && overlayWindow && !overlayWindow.isDestroyed()) overlayWindow.show();
      if (pendingPickerResolver) { pendingPickerResolver(null); pendingPickerResolver = null; }
    });
  });
});

ipcMain.on('notepicker:choose', (e, sel) => {
  if (notePickerWindow && !notePickerWindow.isDestroyed()) notePickerWindow.close();
  if (pendingPickerResolver) { pendingPickerResolver(sel || null); pendingPickerResolver = null; }
});

/* ------------------------------------------------------- 启动 */

app.whenReady().then(() => {
  // 产品要求：去掉原生菜单，窗口外观不暴露 Windows/macOS 原生风格
  Menu.setApplicationMenu(null);
  // 屏幕捕获免弹框，视频=第一个屏幕，音频=系统声音 loopback（豆包同原理）。
  // 防御回退：某些会话（如无头/断开远控）下 WGC 屏幕级枚举会返回空 screen 源，而窗口级仍可用；
  // 业务只消费 loopback 音频轨，视频轨仅为 getDisplayMedia 权限载体，回退到窗口源不改变语义（本机实测取证）。
  session.defaultSession.setDisplayMediaRequestHandler(
    (request, callback) => {
      desktopCapturer.getSources({ types: ['screen', 'window'], thumbnailSize: { width: 320, height: 180 } })
        .then((sources) => {
          const vid = sources.find((s) => String(s.id).startsWith('screen:')) || sources.find((s) => String(s.id).startsWith('window:'));
          callback(vid ? { video: vid, audio: 'loopback' } : {});
        })
        .catch(() => callback({}));
    },
    { useSystemPicker: false }
  );

  ipcMain.handle('app:getServerBase', () => SERVER_BASE);

  createMainWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createMainWindow();
  });
});

app.on('window-all-closed', () => {
  if (asrSession) { try { asrSession.close(); } catch (e) {} asrSession = null; }
  if (process.platform !== 'darwin') app.quit();
});
