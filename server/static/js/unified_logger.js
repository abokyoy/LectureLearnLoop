/**
 * 统一调试日志模块（前端）
 * ========================
 * 所有前端调试信息通过此模块发送到后端 POST /api/debug/log，
 * 最终写入 logs/debug_trace.jsonl（与后端日志同一文件）。
 *
 * 设计原则：
 * - 单例：window.UnifiedLogger 全局唯一
 * - 批量上报：缓冲区满 10 条 或 每 5 秒自动 flush，减少网络请求
 * - 静默失败：日志发送失败不影响页面功能，降级到 console
 * - 页面卸载前强制 flush（beforeunload）
 *
 * 使用示例：
 *   // 快捷函数（推荐）
 *   debugLog('practice', 'generate_start', 'info', {subject: '计算机网络'});
 *   debugLogError('api', 'fetch_failed', err);
 *
 *   // 完整接口
 *   UnifiedLogger.log('knowledge', 'extract_complete', 'success', {count: 5});
 *   UnifiedLogger.flush();  // 强制立即上报
 */

(function () {
  'use strict';

  const FLUSH_INTERVAL_MS = 5000;   // 定时 flush 间隔
  const BUFFER_SIZE_LIMIT = 10;      // 缓冲区满多少条触发 flush
  const API_ENDPOINT = '/api/debug/log';

  /** @type {Array<Object>} */
  let buffer = [];
  let flushTimer = null;
  let isFlushing = false;

  // ---------------------------------------------------------------------------
  // 核心：构建日志条目
  // ---------------------------------------------------------------------------

  /**
   * @param {string} module  功能模块，如 'practice' / 'knowledge' / 'api'
   * @param {string} action  动作名，如 'generate_start' / 'button_click'
   * @param {string} status  'info'|'success'|'error'|'warning'|'debug'
   * @param {Object} data    附加数据
   */
  function buildEntry(module, action, status, data) {
    return {
      timestamp: new Date().toISOString(),
      source: 'frontend',
      module: String(module || 'unknown'),
      action: String(action || 'unknown'),
      status: String(status || 'info'),
      data: data && typeof data === 'object' ? data : {},
      // 辅助字段（后端不写入文件，仅用于前端调试）
      _page: location.pathname,
    };
  }

  // ---------------------------------------------------------------------------
  // 核心：发送到后端
  // ---------------------------------------------------------------------------

  async function sendToBackend(entries) {
    if (!entries || entries.length === 0) return;
    isFlushing = true;
    try {
      const response = await fetch(API_ENDPOINT, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ logs: entries }),
        keepalive: true,   // 允许在页面卸载时也能发出请求
      });
      if (!response.ok) {
        // 静默处理，不中断页面
        console.warn('[UnifiedLogger] 上报失败，HTTP', response.status);
      }
    } catch (err) {
      // 网络不通时降级到 console（开发时可见，生产不影响）
      console.warn('[UnifiedLogger] 上报异常，数据保留在 console:', err.message, entries);
    } finally {
      isFlushing = false;
    }
  }

  // ---------------------------------------------------------------------------
  // 核心：flush 缓冲区
  // ---------------------------------------------------------------------------

  function flush() {
    if (buffer.length === 0) return;
    const batch = buffer.splice(0, buffer.length);  // 取出全部，清空缓冲
    sendToBackend(batch);
  }

  // ---------------------------------------------------------------------------
  // 核心：入队（自动触发 flush）
  // ---------------------------------------------------------------------------

  function enqueue(entry) {
    buffer.push(entry);
    // 缓冲区满 → 立即 flush
    if (buffer.length >= BUFFER_SIZE_LIMIT) {
      flush();
      return;
    }
    // 确保定时器在运行
    if (!flushTimer) {
      flushTimer = setInterval(flush, FLUSH_INTERVAL_MS);
    }
  }

  // ---------------------------------------------------------------------------
  // 公开 API
  // ---------------------------------------------------------------------------

  const UnifiedLogger = {
    /**
     * 记录一条前端调试日志。
     * @param {string} module
     * @param {string} action
     * @param {string} [status='info']
     * @param {Object} [data={}]
     */
    log(module, action, status = 'info', data = {}) {
      enqueue(buildEntry(module, action, status, data));
    },

    /** 快捷记录 info 级别 */
    info(module, action, data = {}) {
      enqueue(buildEntry(module, action, 'info', data));
    },

    /** 快捷记录 success 级别 */
    success(module, action, data = {}) {
      enqueue(buildEntry(module, action, 'success', data));
    },

    /** 快捷记录 error 级别（自动附加 error.message） */
    error(module, action, errorOrData = {}, extraData = {}) {
      const data = { ...extraData };
      if (errorOrData instanceof Error) {
        data.error = errorOrData.message;
        data.error_stack = errorOrData.stack ? errorOrData.stack.substring(0, 300) : '';
      } else if (typeof errorOrData === 'object') {
        Object.assign(data, errorOrData);
      }
      enqueue(buildEntry(module, action, 'error', data));
    },

    /** 快捷记录 warning 级别 */
    warn(module, action, data = {}) {
      enqueue(buildEntry(module, action, 'warning', data));
    },

    /** 强制立即上报缓冲区内容 */
    flush() {
      flush();
    },

    /** 获取当前缓冲区条数（调试用） */
    bufferSize() {
      return buffer.length;
    },
  };

  // 挂载到 window
  window.UnifiedLogger = UnifiedLogger;

  // 全局快捷函数
  window.debugLog = (module, action, status, data) => UnifiedLogger.log(module, action, status, data);
  window.debugLogError = (module, action, error, data) => UnifiedLogger.error(module, action, error, data);

  // ---------------------------------------------------------------------------
  // 页面生命周期：卸载前强制 flush
  // ---------------------------------------------------------------------------

  window.addEventListener('beforeunload', () => {
    if (buffer.length > 0) {
      // 使用 sendBeacon 确保页面关闭时也能发出
      const batch = buffer.splice(0, buffer.length);
      const blob = new Blob([JSON.stringify({ logs: batch })], { type: 'application/json' });
      navigator.sendBeacon(API_ENDPOINT, blob);
    }
  });

  // 启动定时器
  flushTimer = setInterval(flush, FLUSH_INTERVAL_MS);

  // 初始化日志（页面加载完成时记录一条，证明模块已就绪）
  document.addEventListener('DOMContentLoaded', () => {
    UnifiedLogger.log('system', 'unified_logger_initialized', 'info', {
      page: location.pathname,
    });
  });

})();  // IIFE 结束
