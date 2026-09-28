/**
 * 预加载脚本：向渲染进程暴露最小安全接口。
 * - llShell: 基础信息
 * - llAsr:   流式语音识别（PCM 帧上行 + 字幕事件下行，WS 在主进程）
 * - llCapture: 屏幕取帧 + 框选截屏窗口
 */
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('llShell', {
  getServerBase: () => ipcRenderer.invoke('app:getServerBase'),
  openOverlay: () => ipcRenderer.invoke('overlay:open'),
});

contextBridge.exposeInMainWorld('llAsr', {
  /** 开启会话：cfg 来自 /api/asr/config 的 data */
  start: (cfg) => ipcRenderer.invoke('asr:start', cfg),
  /** 上行一帧 16k Int16LE PCM（ArrayBuffer） */
  sendChunk: (arrayBuffer) => ipcRenderer.send('asr:chunk', arrayBuffer),
  stop: () => ipcRenderer.invoke('asr:stop'),
  /** 订阅字幕事件：cb({type:'open'|'interim'|'final'|'error'|'close', text}) */
  onResult: (cb) => {
    const listener = (_e, ev) => cb(ev);
    ipcRenderer.on('asr:result', listener);
    return () => ipcRenderer.removeListener('asr:result', listener);
  },
});

contextBridge.exposeInMainWorld('llCapture', {
  /** 抓取全屏，返回 {dataUrl, width, height}（物理像素） */
  getScreen: () => ipcRenderer.invoke('capture:getScreen'),
  /** 打开框选窗口，用户选完后 resolve {x,y,width,height}（CSS 像素）或 null */
  selectRegion: () => ipcRenderer.invoke('capture:selectRegion'),
  /** 直接截取整个屏幕 */
  fullScreen: () => ipcRenderer.invoke('capture:fullScreen'),
});

// 悬浮窗拖拽 / 收起 / 关闭（overlay.html 使用）；两者均销毁主进程窗口，避免黑浮层残留
contextBridge.exposeInMainWorld('llOverlayDrag', (dx, dy) => ipcRenderer.send('overlay:drag', dx, dy));
contextBridge.exposeInMainWorld('overlayMin', () => ipcRenderer.invoke('overlay:close'));
contextBridge.exposeInMainWorld('overlayClose', () => ipcRenderer.invoke('overlay:close'));

// 框选窗口专用（capture.html）
contextBridge.exposeInMainWorld('llCaptureSel', {
  onImage: (cb) => {
    const l = (_e, s) => cb(s);
    ipcRenderer.on('capture:image', l);
    return () => ipcRenderer.removeListener('capture:image', l);
  },
  submit: (rect) => ipcRenderer.send('capture:region-selected', rect),
  cancel: () => ipcRenderer.send('capture:region-selected', null),
});

// 二期：学习笔记选择窗（悬浮窗/主面板录音前调用）
contextBridge.exposeInMainWorld('llNotePicker', {
  /** 弹出独立选择窗；resolve {action:'open'|'new', path, name} 或 null（取消） */
  open: () => ipcRenderer.invoke('notepicker:open'),
});

// 选择页专用（note_picker.html）
contextBridge.exposeInMainWorld('llNotePickerSel', {
  choose: (sel) => ipcRenderer.send('notepicker:choose', sel),
  cancel: () => ipcRenderer.send('notepicker:choose', null),
});
