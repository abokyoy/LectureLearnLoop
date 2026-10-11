/**
 * LectureLearnLoop Electron 主进程。
 *
 * P2：主窗口加载 Flask 服务端页面。
 * P4：悬浮录音窗（/overlay）、Deepgram 流式 WS 代理（asr_proxy）、框选截屏。
 */
const { app, BrowserWindow, ipcMain, session, desktopCapturer, screen, Menu } = require('electron');
const path = require('path');
const asr = require('./asr_proxy');

const SERVER_BASE = process.env.LL_SERVER || 'http://127.0.0.1:6001';

let mainWindow = null;
let overlayWindow = null;
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
        '<h2 style="font-family:sans-serif">⚠️ 无法连接服务端 ' + SERVER_BASE + '</h2>' +
        '<p style="font-family:sans-serif">请先运行 <code>python server/app.py</code>，然后重启本应用。</p>'));
    }
  });
  mainWindow.webContents.on('did-finish-load', () => { serverDownRetries = 0; });

  loadServerPage(mainWindow);
  mainWindow.on('closed', () => { mainWindow = null; });
}

/* ------------------------------------------------------- 悬浮录音窗（P4） */

function createOverlayWindow() {
  if (overlayWindow && !overlayWindow.isDestroyed()) {
    overlayWindow.show();
    return;
  }
  const wa = screen.getPrimaryDisplay().workArea;
  overlayWindow = new BrowserWindow({
    width: 360,
    height: 560,   // 二期：新增 暂停/完成 按钮与“正在保存到”横幅，微增高度容纳
    x: wa.x + wa.width - 380,
    y: wa.y + 40,
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
    },
  });
  overlayWindow.setAlwaysOnTop(true, 'screen-saver');
  overlayWindow.loadURL(SERVER_BASE + '/overlay');
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
ipcMain.on('overlay:drag', (e, dx, dy) => {
  if (!overlayWindow || overlayWindow.isDestroyed()) return;
  const [x, y] = overlayWindow.getPosition();
  overlayWindow.setPosition(Math.round(x + dx), Math.round(y + dy));
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
  // 屏幕捕获免弹框，视频=第一个屏幕，音频=系统声音 loopback（豆包同原理）
  session.defaultSession.setDisplayMediaRequestHandler(
    (request, callback) => {
      desktopCapturer.getSources({ types: ['screen'], thumbnailSize: { width: 320, height: 180 } })
        .then((sources) => callback({ video: sources[0], audio: 'loopback' }))
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
