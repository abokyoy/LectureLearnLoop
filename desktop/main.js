/**
 * LectureLearnLoop Electron 主进程。
 *
 * P2：主窗口加载 Flask 服务端页面。
 * P4：悬浮录音窗（/overlay）、Deepgram 流式 WS 代理（asr_proxy）、框选截屏。
 */
const { app, BrowserWindow, ipcMain, session, desktopCapturer, screen, Menu, net } = require('electron');
const path = require('path');
const fs = require('fs');
const asr = require('./asr_proxy');
const xzVoice = require('./xz_voice');
const xzSpeech = require('./xz_speech');

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
let voiceWindow = null;   // 电脑小智语音窗（协议/编解码在主进程，此窗只采集/播放/UI）
let xzEngine = null;      // XzVoiceEngine 实例

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

/* ------------------------------------------------------- 电脑小智（2026-11-05） */
// 冒充 ESP32 设备连小智云：OTA/WS/opus/打断全在主进程 xz_voice.js（可 node 断言直测），
// 这里只注入 Electron 侧依赖：net 版 httpPost（自走系统代理，外网 OTA 需要）、语音窗口路由。
function netHttpPost(url, body, headers) {
  return new Promise((resolve, reject) => {
    const req = net.request({ method: 'POST', url });
    Object.keys(headers || {}).forEach((k) => { try { req.setHeader(k, String(headers[k])); } catch (e) {} });
    req.on('response', (res) => {
      let text = '';
      res.setEncoding('utf8');
      res.on('data', (c) => { text += c; });
      res.on('end', () => resolve({ status: res.statusCode, text }));
      res.on('error', reject);
    });
    req.on('error', reject);
    req.write(body);
    req.end();
  });
}

function createVoiceWindow() {
  if (voiceWindow && !voiceWindow.isDestroyed()) { voiceWindow.show(); voiceWindow.focus(); return; }
  const isMac = process.platform === 'darwin';
  voiceWindow = new BrowserWindow({
    width: 520,
    height: 680,
    title: 'AI老师语音上课',
    autoHideMenuBar: true,
    backgroundColor: '#FAF7F2',
    titleBarStyle: 'hidden',
    ...(isMac ? { trafficLightPosition: { x: 16, y: 14 } } : { titleBarOverlay: { color: '#FFFFFF', symbolColor: '#78716C', height: 44 } }),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      // 采集/播放/定时器在窗未聚焦时也必须跑（上课期间用户必然在其它窗口），同悬浮窗口径
      backgroundThrottling: false,
    },
  });
  // 本地页非 http/localhost，不会命中主窗口的 insecure-origin 开关；但 Chromium 对 file://
  // 的 mediaDevices 默认放行，这里再显式授权音频一次，防后续权限策略收紧。
  voiceWindow.loadFile(path.join(__dirname, 'xiaozhi_voice.html'));
  voiceWindow.on('closed', () => {
    voiceWindow = null;
    // 窗关了就下课：断 WS/释 codec，不留幽灵会话（面板设"点开始才建通道"的直播形态语义）
    if (xzEngine) { try { xzEngine.lessonStop(); } catch (e) {} }
  });
}

/** 弹语音窗；autoStart=true 时页面就绪后代按「开始上课」（上课指令仍由语音窗自身发出，守住 sender 安全边界） */
function openVoicePanel(autoStart) {
  const isNew = !(voiceWindow && !voiceWindow.isDestroyed());
  createVoiceWindow();
  if (!autoStart) return true;
  const fire = () => {
    try { if (voiceWindow && !voiceWindow.isDestroyed()) voiceWindow.webContents.send('xz:autostart', {}); } catch (e) { /* noop */ }
  };
  if (isNew) voiceWindow.webContents.once('did-finish-load', fire);
  else fire();   // 窗已开着：页面早加载完，直接补一发
  return true;
}

ipcMain.handle('xz:openPanel', () => openVoicePanel(false));
// 黑板页「开始上课」（2026-11-05 入口合并）：开窗 + 自动开课一步到位
ipcMain.handle('xz:openPanelStart', () => openVoicePanel(true));

/**
 * 主进程 → 本服务器 API 的唯一出口（v0.2.2 抽公共）：带主窗口 token、解双层契约只回 data。
 * serverApi（开课/绑定链路）与字幕上报共用这一条，避免两套鉴权/解包口径漂移。
 * 失败一律 throw（调用方自决降级），超时 10s（CodeReview P2-4：服务僵死不能挂死流程）。
 */
async function serverRequest(method, p, body) {
  const tkn = await getMainAuthToken();
  const headers = { 'Content-Type': 'application/json' };
  if (tkn) headers['Authorization'] = 'Bearer ' + tkn;
  const ctrl = new AbortController();
  const timer = setTimeout(() => { try { ctrl.abort(); } catch (e) {} }, 10000);
  let res, j = null;
  try {
    res = await fetch(SERVER_BASE + p, {
      method: method, headers: headers, body: body === undefined ? undefined : JSON.stringify(body),
      signal: ctrl.signal,
    });
    try { j = await res.json(); } catch (e) { /* 空/非 JSON 响应 */ }
  } finally { clearTimeout(timer); }
  if (!res || !j || j.success !== true) {
    throw new Error(String((j && j.error) || ('HTTP ' + (res ? res.status : '网络异常'))));
  }
  return j.data;
}

// 字幕上报器（口播句=老师、识别句=学生，失败静默）：setupXzVoice 里创建，注入 serverRequest 便于单测
let boardSpeech = null;

function setupXzVoice() {
  boardSpeech = xzSpeech.createSpeechReporter({ request: serverRequest, now: () => Date.now() });
  xzEngine = xzVoice.createXzVoice({
    configDir: app.getPath('userData'),
    ipc: ipcMain,
    httpPost: netHttpPost,
    now: () => Date.now(),
    // 账号级小智身份（2026-11-05 v0.2.1）：带主窗口 token 请求本服务器 API，
    // 解包双层契约只把 data 交给引擎；失败 throw 由引擎降级处置（local-legacy/引导）。
    serverApi: (method, p, body) => serverRequest(method, p, body),
    // 安全：语音 IPC 只接语音窗 sender。主窗口加载的是远程 Flask 页，
    // 共享 preload 不能把驱动麦/上下课的能力交给远程内容（CodeReview 警告⑨）
    allowSender: (s) => {
      try { return !!(voiceWindow && !voiceWindow.isDestroyed() && s === voiceWindow.webContents); }
      catch (e) { return false; }
    },
    windowOps: {
      send: (ch, payload) => {
        if (voiceWindow && !voiceWindow.isDestroyed()) voiceWindow.webContents.send('xz:' + ch, payload);
      },
    },
    onEvent: (evt) => {
      // 课堂状态relay给主窗（黑板页指示灯/按钮文案）：只读转发，不给远程内容控制能力
      if (evt && evt.type === 'state') {
        try { if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send('xz:voice-state', evt.state); } catch (e) { /* noop */ }
      }
      // 字幕上报（v0.2.2 两段式黑板）：tts 逐句 = 老师口播，stt = 学生发言；
      // 真机 ESP32 上课不走这条路（服务端拿不到口播文本，黑板页自动退化为卡片流）
      if (boardSpeech) { try { boardSpeech.onEvent(evt); } catch (e) { /* 上报异常不断链 */ } }
      // 事件流水落盘供排障/实弹留证（与 logs/debug_trace 同思路，userData 下免权限问题）
      try {
        fs.appendFileSync(path.join(app.getPath('userData'), 'xz_voice_events.log'),
          JSON.stringify({ ts: new Date().toISOString(), evt }) + '\n');
      } catch (e) { /* 日志失败不断链 */ }
    },
  });
}

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

  setupXzVoice();

  createMainWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createMainWindow();
  });
});

app.on('window-all-closed', () => {
  if (asrSession) { try { asrSession.close(); } catch (e) {} asrSession = null; }
  if (xzEngine) { try { xzEngine.dispose(); } catch (e) {} xzEngine = null; }
  if (process.platform !== 'darwin') app.quit();
});
