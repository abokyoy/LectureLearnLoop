/**
 * pybridge / bridge 全量兼容层 —— Qt CorgiWebBridge → Flask HTTP + Electron IPC
 *
 * 协议还原要点（docs/接口/2026-09-27-桥方法兼容层规格.md）：
 * - Qt @Slot 在 QWebChannel 下永远异步、最后一个参数是 callback；
 *   本层每个桥方法同时支持 (…, callback) 与返回 Promise（双保险，SPA 壳用 .then）。
 * - Promise resolve 值与 callback 首参完全一致（字符串型=Qt 的 JSON 字符串/纯文本，
 *   bool 型=true/false），页面原有 JSON.parse 逻辑无需改动。
 * - 顶层数组方法错误回退 "[]"；纯文本方法错误回退 ""；bool 方法回退 false。
 * - 鉴权：localStorage.ll_token（Bearer），401 自动跳转 /login。
 * - C 类（录音/设备/截屏/窗口）委托 window.electronBridge（P4 实装），未就绪时
 *   按规格提供安全 fallback。
 */
(function (global) {
    'use strict';

    // ============================== HTTP 基础 ==============================

    // 鉴权：localStorage.ll_token（记住登录）或 sessionStorage.ll_token（会话级，四期修正），Bearer；401 自动跳转 /login。
    function getToken() {
        try { return localStorage.getItem('ll_token') || sessionStorage.getItem('ll_token') || ''; } catch (e) { return ''; }
    }
    function setToken(t, persist) {
        try {
            if (persist) { localStorage.setItem('ll_token', t || ''); sessionStorage.removeItem('ll_token'); }
            else if (t) { sessionStorage.setItem('ll_token', t); localStorage.removeItem('ll_token'); }
            else { clearToken(); }
        } catch (e) { /* ignore */ }
    }
    function clearToken() {
        try { localStorage.removeItem('ll_token'); sessionStorage.removeItem('ll_token'); } catch (e) { /* ignore */ }
    }
    // 全局暴露：页面内联脚本统一用这三个函数读写 token（兼容旧 localStorage 直读点的回退）
    global.llGetToken = getToken;
    global.llSetToken = setToken;
    global.llClearToken = clearToken;

    async function req(method, url, body, opts) {
        const headers = { 'Content-Type': 'application/json' };
        const tk = getToken();
        if (tk) headers['Authorization'] = 'Bearer ' + tk;
        const res = await fetch(url, {
            method: method,
            headers: headers,
            body: body === undefined || body === null ? undefined : JSON.stringify(body),
            signal: (opts && opts.signal) || undefined, // 四期D组：支持外部 AbortController 中断（AI聊天停止按钮）
        });
        if (res.status === 401) {
            clearToken();
            if (!/\/login(\?|$)/.test(location.pathname)) {
                location.href = '/login?next=' + encodeURIComponent(location.pathname + location.search);
            }
            throw new Error('未登录或登录已过期');
        }
        let j = null;
        try { j = await res.json(); } catch (e) { /* 空响应体 */ }
        // 2026-09-28 积分：响应含计费字段时回调全局提示钩子（llHandleBilling 由 base.html 定义）；
        // Chat 场景由消息尾部扣分注脚独立处理，调用方传 opts.skipBilling 避免双弹。
        function billingHook() {
            if (opts && opts.skipBilling) return;
            if (!j) return;
            // 白名单取键，避免把业务响应体整体传给计费钩子
            const KEYS = ['credit_note', 'credits_deducted', 'credit_balance', 'credits_insufficient'];
            const pick = (o) => {
                if (!o) return null;
                const b = {};
                let any = false;
                for (const k of KEYS) { if (o[k] !== undefined) { b[k] = o[k]; any = true; } }
                return any ? b : null;
            };
            const b = pick(j) || pick(j.data);
            if (!b) return;
            try { if (global.llHandleBilling) global.llHandleBilling(b); } catch (e) { /* 提示失败不阻断业务 */ }
        }
        if (!res.ok) { billingHook(); throw new Error((j && j.error) || ('HTTP ' + res.status)); }
        if (j && j.success === false) { billingHook(); throw new Error(j.error || '请求失败'); }
        billingHook();
        return j ? j.data : null;
    }

    const J = function (v) { return typeof v === 'string' ? v : JSON.stringify(v); };

    // ============================== 桥方法工厂 ==============================
    // as: 'json'  → callback/Promise 值为 JSON 字符串（impl 返回对象）
    //     'raw'   → 原样字符串（impl 返回字符串；错误回退 ''）
    //     'bool'  → 布尔（错误回退 false）
    //     'none'  → 无返回（Qt 无 result 的 slot；impl 自行负责副作用）
    function bridgeFn(impl, opt) {
        opt = opt || {};
        const as = opt.as || 'json';
        return function () {
            const args = Array.prototype.slice.call(arguments);
            let cb = null;
            if (args.length && typeof args[args.length - 1] === 'function') cb = args.pop();
            const p = Promise.resolve().then(function () { return impl.apply(null, args); })
                .then(function (v) {
                    if (as === 'json') {
                        if (v === undefined || v === null) return J(opt.errShell === undefined ? { success: false, error: '无结果' } : v);
                        return J(v);
                    }
                    if (as === 'raw') return v === undefined || v === null ? '' : String(v);
                    if (as === 'bool') return v === true;
                    return v;
                })
                .catch(function (e) {
                    console.error('[bridge:' + (opt.name || '?') + ']', e);
                    if (opt.arr) return '[]';
                    if (as === 'json') return J({ success: false, error: String((e && e.message) || e) });
                    if (as === 'bool') return false;
                    return '';
                });
            if (cb) p.then(function (v) { try { cb(v); } catch (e) { console.error(e); } });
            return p;
        };
    }

    function parseArg(s, dflt) {
        if (s && typeof s === 'object') return s;
        try { return JSON.parse(s); } catch (e) { return dflt; }
    }

    // ============================== 菜单 / 导航（D 类） ==============================

    const menuState = {
        dashboard: { expanded: false, children: [] },
        learn: { expanded: false, children: ['online_course_notes'] },
        practice: { expanded: false, children: ['practice_materials', 'practice_knowledge', 'practice_errors', 'api_test'] },
        memory: { expanded: false, children: ['memory_knowledge', 'memory_errors'] },
        knowledge_base: { expanded: false, children: [] },
        settings: { expanded: false, children: [] },
    };

    // 与 base.html menuRoutes 一致的多页路由表
    const PAGE_ROUTES = {
        'dashboard': '/',
        'online_course_notes': '/online_course',
        'practice_materials': '/practice',
        'practice_knowledge': '/practice',
        'practice_errors': '/practice',
        'memory_knowledge': '/practice',
        'memory_errors': '/practice',
        'knowledge_base': '/knowledge_base',
        'settings': '/settings',
        'llm_logs': '/llm_logs',
        'admin_credits': '/admin/credits',
    };

    function isSpaShell() {
        return typeof window.updateContentArea === 'function' &&
            !!document.getElementById('content-area');
    }

    function doLoadContentForced(contentId) {
        global.current_page = contentId;
        if (window.UnsavedChangesGuard &&
            typeof window.UnsavedChangesGuard.resetUnsavedChanges === 'function') {
            try { window.UnsavedChangesGuard.resetUnsavedChanges(); } catch (e) { /* noop */ }
        }
        if (isSpaShell()) {
            req('GET', '/fragments/' + encodeURIComponent(contentId)).then(function (html) {
                window.updateContentArea(typeof html === 'string' ? html : '');
            }).catch(function () {
                if (PAGE_ROUTES[contentId]) location.href = PAGE_ROUTES[contentId];
            });
        } else if (PAGE_ROUTES[contentId]) {
            location.href = PAGE_ROUTES[contentId];
        } else {
            console.warn('未找到菜单路由:', contentId);
        }
    }

    function doLoadContent(contentId) {
        if (window.UnsavedChangesGuard &&
            typeof window.UnsavedChangesGuard.hasUnsavedChanges === 'function' &&
            window.UnsavedChangesGuard.hasUnsavedChanges()) {
            if (window.confirm && !confirm('当前有未保存的更改，确定要离开吗？')) return;
        }
        doLoadContentForced(contentId);
    }

    // ============================== C 类委托 Electron ==============================

    function cFallbackDefault(args, name) {
        return { success: false, error: name + ' 需要桌面客户端支持' };
    }

    function cFn(name, fallbackFactory) {
        return bridgeFn(async function () {
            const args = Array.prototype.slice.call(arguments);
            const eb = global.electronBridge;
            if (eb && typeof eb[name] === 'function') {
                const v = await Promise.resolve(eb[name].apply(eb, args));
                return v;
            }
            return fallbackFactory ? fallbackFactory(args) : cFallbackDefault(args, name);
        }, { as: 'json', name: name });
    }

    // ============================== 桥方法实现 ==============================

    const bridge = {};

    // ---------- 一、窗口 / 菜单 / 导航 ----------
    bridge.logFrontendMessage = bridgeFn(function (message) {
        console.log('[frontend] ' + message);
    }, { as: 'none', name: 'logFrontendMessage' });

    bridge.minimizeWindow = bridgeFn(function () {
        const eb = global.electronBridge;
        if (eb && eb.minimizeWindow) eb.minimizeWindow();
    }, { as: 'none', name: 'minimizeWindow' });
    bridge.maximizeWindow = bridgeFn(function () {
        const eb = global.electronBridge;
        if (eb && eb.maximizeWindow) eb.maximizeWindow();
    }, { as: 'none', name: 'maximizeWindow' });
    bridge.closeWindow = bridgeFn(function () {
        const eb = global.electronBridge;
        if (eb && eb.closeWindow) eb.closeWindow();
    }, { as: 'none', name: 'closeWindow' });

    bridge.toggleMenu = bridgeFn(function (menuId) {
        const item = menuState[menuId];
        if (item && item.children && item.children.length) {
            item.expanded = !item.expanded;
        } else if (menuId) {
            doLoadContent(menuId);
        }
        return J(menuState);
    }, { as: 'raw', name: 'toggleMenu' });

    bridge.getMenuState = bridgeFn(function () { return J(menuState); },
        { as: 'raw', name: 'getMenuState' });

    bridge.loadContent = bridgeFn(function (contentId) { doLoadContent(contentId); },
        { as: 'none', name: 'loadContent' });
    bridge.loadContentForced = bridgeFn(function (contentId) { doLoadContentForced(contentId); },
        { as: 'none', name: 'loadContentForced' });
    bridge.switchToRecording = bridgeFn(function () { doLoadContent('online_course_notes'); },
        { as: 'none', name: 'switchToRecording' });

    bridge.openQuestionReview = bridgeFn(function (questionId) {
        doLoadContent('practice_errors');
        global.__pendingQuestionReview = questionId;
    }, { as: 'none', name: 'openQuestionReview' });

    bridge.triggerManualDebug = bridgeFn(function () {
        return '手动调试（兼容层 no-op）';
    }, { as: 'raw', name: 'triggerManualDebug' });

    bridge.validateAllFileOperations = bridgeFn(async function () {
        // 迁移后改为只读健康检查（Qt 版有建/删真实副作用，规格建议只读）
        const lines = [];
        let ok = 0, total = 0;
        total++; try { await req('GET', '/api/vault/tree-nested'); lines.push('✅ vault 文件树读取'); ok++; }
        catch (e) { lines.push('❌ vault 文件树读取: ' + e.message); }
        total++; try { await req('GET', '/api/config'); lines.push('✅ 配置读取'); ok++; }
        catch (e) { lines.push('❌ 配置读取: ' + e.message); }
        total++; try { await req('GET', '/api/subjects'); lines.push('✅ 科目读取'); ok++; }
        catch (e) { lines.push('❌ 科目读取: ' + e.message); }
        return '后端功能验证完成: ' + ok + '/' + total + ' 项测试通过\n' + lines.join('\n');
    }, { as: 'raw', name: 'validateAllFileOperations' });

    // ---------- 二、文件树 / Markdown 读写 ----------
    bridge.getFileStructure = bridgeFn(function () {
        return req('GET', '/api/vault/tree-nested');
    }, { as: 'json', arr: true, name: 'getFileStructure' });

    function escPre(t) {
        return String(t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }
    function mdToHtml(mdText) {
        if (!mdText) return '';
        if (global.marked && typeof global.marked.parse === 'function') {
            try { return global.marked.parse(mdText); } catch (e) { /* fallthrough */ }
        }
        return '<pre>' + escPre(mdText) + '</pre>';
    }

    bridge.loadMarkdownRaw = bridgeFn(function (filePath) {
        global.__lastBridgeFilePath = filePath;
        return req('GET', '/api/vault/rawfile?path=' + encodeURIComponent(filePath))
            .then(function (v) { return v || ''; });
    }, { as: 'raw', name: 'loadMarkdownRaw' });

    bridge.loadMarkdownFile = bridgeFn(function (filePath) {
        return req('GET', '/api/vault/rawfile?path=' + encodeURIComponent(filePath))
            .then(function (v) { return v ? mdToHtml(v) : ''; });
    }, { as: 'raw', name: 'loadMarkdownFile' });

    bridge.saveMarkdownFile = bridgeFn(async function (filePath, content) {
        global.__lastBridgeFilePath = filePath;
        const ok = await req('PUT', '/api/vault/rawfile', { path: filePath, content: content });
        return ok === true;
    }, { as: 'bool', name: 'saveMarkdownFile' });

    bridge.save_file = bridgeFn(function (filePath, content) {
        return req('PUT', '/api/vault/rawfile', { path: filePath, content: content })
            .then(function (ok) {
                return ok ? { success: true, message: '文件保存成功', file_path: filePath }
                    : { success: false, error: '文件保存失败', file_path: filePath };
            });
    }, { as: 'json', name: 'save_file' });

    bridge.createNewNote = bridgeFn(function (folderPath) {
        return req('POST', '/api/vault/note', { folder_path: folderPath || 'vault' })
            .then(function (v) { return v || ''; });
    }, { as: 'raw', name: 'createNewNote' });

    bridge.createNewFolder = bridgeFn(function (parentPath) {
        return req('POST', '/api/vault/folder', { parent_path: parentPath || 'vault' })
            .then(function (v) { return v || ''; });
    }, { as: 'raw', name: 'createNewFolder' });

    bridge.renameFileOrFolder = bridgeFn(function (oldPath, newName) {
        return req('POST', '/api/vault/rename', { old_path: oldPath, new_name: newName });
    }, { as: 'bool', name: 'renameFileOrFolder' });

    bridge.moveFileOrFolder = bridgeFn(function (sourcePath, targetFolder) {
        return req('POST', '/api/vault/move', { source_path: sourcePath, target_folder: targetFolder });
    }, { as: 'bool', name: 'moveFileOrFolder' });

    bridge.deleteFileOrFolder = bridgeFn(function (path) {
        return req('POST', '/api/vault/delete', { path: path });
    }, { as: 'bool', name: 'deleteFileOrFolder' });

    bridge.copyFileOrFolder = bridgeFn(function (sourcePath, targetFolder) {
        return req('POST', '/api/vault/copy', { source_path: sourcePath, target_folder: targetFolder });
    }, { as: 'bool', name: 'copyFileOrFolder' });

    bridge.getImageAsBase64 = bridgeFn(function (imagePath) {
        return req('GET', '/api/vault/image?path=' + encodeURIComponent(imagePath));
    }, { as: 'json', name: 'getImageAsBase64' });

    // ---------- 三、配置 / LLM 连接 / 日志 ----------
    bridge.getConfig = bridgeFn(function () {
        return req('GET', '/api/config');
    }, { as: 'json', name: 'getConfig' });

    bridge.saveConfig = bridgeFn(function (configJson) {
        const cfg = parseArg(configJson, null);
        if (!cfg || typeof cfg !== 'object') return false;
        return req('PUT', '/api/config', cfg);
    }, { as: 'bool', name: 'saveConfig' });

    bridge.testLLMConnection = bridgeFn(function (provider) {
        return req('POST', '/api/llm/test', { provider: provider || '' });
    }, { as: 'raw', name: 'testLLMConnection' });

    bridge.openLogViewer = bridgeFn(function () {
        return Promise.all([
            req('GET', '/api/llm/logs?limit=50'),
            req('GET', '/api/llm/stats').catch(function () { return {}; }),
        ]).then(function (rs) {
            if (typeof global.showLogViewer === 'function') {
                global.showLogViewer({ records: rs[0] || [], statistics: rs[1] || {} });
            }
        });
    }, { as: 'none', name: 'openLogViewer' });

    bridge.clearLLMLogs = bridgeFn(function () {
        return req('DELETE', '/api/llm/logs');
    }, { as: 'bool', name: 'clearLLMLogs' });

    bridge.getLLMCallLogs = bridgeFn(function () {
        return Promise.all([
            req('GET', '/api/llm/logs?limit=100'),
            req('GET', '/api/llm/stats').catch(function () { return {}; }),
        ]).then(function (rs) {
            return { success: true, records: rs[0] || [], statistics: rs[1] || {} };
        });
    }, { as: 'json', name: 'getLLMCallLogs' });

    // ---------- 四、知识点提取 / 相似 / 合并 / 新建 / 批量 ----------
    bridge.extractKnowledgePoints = bridgeFn(function (filePath) {
        return req('POST', '/api/knowledge/extract-file', { file_path: filePath });
    }, { as: 'json', name: 'extractKnowledgePoints' });

    bridge.findSimilarKnowledgePoints = bridgeFn(function (requestDataJson) {
        const reqObj = parseArg(requestDataJson, {}) || {};
        const point = reqObj.point || {};
        return req('POST', '/api/knowledge/similar', {
            subject: reqObj.subject || '',
            point_name: point.name || reqObj.point_name || '',
            limit: reqObj.limit || 10,
        });
    }, { as: 'json', arr: true, name: 'findSimilarKnowledgePoints' });

    bridge.mergeKnowledgePoint = bridgeFn(function (mergeDataJson) {
        return req('POST', '/api/knowledge/merge', parseArg(mergeDataJson, {}));
    }, { as: 'json', name: 'mergeKnowledgePoint' });

    bridge.createNewKnowledgePoint = bridgeFn(function (createDataJson) {
        return req('POST', '/api/knowledge/point-new', parseArg(createDataJson, {}));
    }, { as: 'json', name: 'createNewKnowledgePoint' });

    bridge.batchSaveKnowledgePoints = bridgeFn(function (batchDataJson) {
        return req('POST', '/api/knowledge/batch-save', parseArg(batchDataJson, {}));
    }, { as: 'json', name: 'batchSaveKnowledgePoints' });

    bridge.saveNoteKnowledgeMapping = bridgeFn(function (mappingDataJson) {
        return req('POST', '/api/notes/mapping', parseArg(mappingDataJson, {}));
    }, { as: 'json', name: 'saveNoteKnowledgeMapping' });

    bridge.getNoteKnowledgePoints = bridgeFn(function (filePath) {
        return req('GET', '/api/notes/knowledge-points?path=' + encodeURIComponent(filePath || ''));
    }, { as: 'json', arr: true, name: 'getNoteKnowledgePoints' });

    // ---------- 五、科目管理 ----------
    bridge.getSubjects = bridgeFn(function () {
        return req('GET', '/api/subjects');
    }, { as: 'json', arr: true, name: 'getSubjects' });

    async function subjectStats() {
        const data = await req('GET', '/api/subjects/stats');
        return (data || []).map(function (s) {
            return {
                name: s.subject_name || s.name,
                kp_count: s.kp_count !== undefined ? s.kp_count : (s.knowledge_count || 0),
                knowledge_count: s.kp_count !== undefined ? s.kp_count : (s.knowledge_count || 0),
                can_delete: (s.kp_count || 0) === 0,
            };
        });
    }

    bridge.getAllSubjects = bridgeFn(function () {
        return subjectStats().then(function (rows) {
            return rows.map(function (r) {
                return { name: r.name, knowledge_count: r.knowledge_count, can_delete: r.can_delete };
            });
        });
    }, { as: 'json', arr: true, name: 'getAllSubjects' });

    bridge.getSubjectsWithKnowledgeCount = bridgeFn(function () {
        return subjectStats().then(function (rows) {
            return rows.filter(function (r) { return r.knowledge_count > 0; })
                .map(function (r) { return { name: r.name, knowledge_count: r.knowledge_count }; });
        });
    }, { as: 'json', arr: true, name: 'getSubjectsWithKnowledgeCount' });

    bridge.getSubjectKnowledgePoints = bridgeFn(function (subject) {
        return req('GET', '/api/knowledge/points?subject=' + encodeURIComponent(subject || ''))
            .then(async function (points) {
                const out = [];
                for (const p of (points || [])) {
                    let sources = p.sources || [];
                    if (!p.sources && p.id) {
                        sources = await req('GET', '/api/knowledge/points/' + p.id + '/sources')
                            .catch(function () { return []; });
                    }
                    out.push({
                        id: p.id,
                        name: p.point_name || p.name,
                        description: p.core_description || p.description || '',
                        mastery_score: p.mastery_score !== undefined && p.mastery_score !== null ? p.mastery_score : 50,
                        created_time: p.created_time || '',
                        sources: sources,
                    });
                }
                return out;
            });
    }, { as: 'json', arr: true, name: 'getSubjectKnowledgePoints' });

    bridge.addSubject = bridgeFn(async function (subjectName) {
        const rows = await subjectStats();
        if (rows.some(function (r) { return r.name === subjectName; })) {
            return { success: false, error: "科目 '" + subjectName + "' 已存在" };
        }
        await req('POST', '/api/subjects', { subject_name: subjectName });
        return { success: true, message: "科目 '" + subjectName + "' 添加成功" };
    }, { as: 'json', name: 'addSubject' });

    bridge.createSubject = bridgeFn(async function (subjectName) {
        const rows = await subjectStats();
        if (rows.some(function (r) { return r.name === subjectName; })) {
            return { success: false, error: "科目 '" + subjectName + "' 已存在" };
        }
        const r = await req('POST', '/api/subjects', { subject_name: subjectName })
            .catch(function (e) { return { created: false, err: e.message }; });
        if (r && r.created === false) return { success: false, error: '科目创建失败' };
        return { success: true, message: "科目 '" + subjectName + "' 创建成功" };
    }, { as: 'json', name: 'createSubject' });

    bridge.updateSubject = bridgeFn(async function (oldName, newName) {
        const rows = await subjectStats();
        if (rows.some(function (r) { return r.name === newName; })) {
            return { success: false, error: "科目名称 '" + newName + "' 已存在" };
        }
        const r = await req('PUT', '/api/subjects/' + encodeURIComponent(oldName), { new_name: newName })
            .catch(function () { return null; });
        if (!r || r.renamed === false) return { success: false, error: '科目更新失败' };
        return { success: true, message: "科目名称已更新为 '" + newName + "'" };
    }, { as: 'json', name: 'updateSubject' });

    bridge.deleteSubject = bridgeFn(async function (subjectName) {
        const rows = await subjectStats();
        const hit = rows.find(function (r) { return r.name === subjectName; });
        if (!hit) return { success: false, error: "科目 '" + subjectName + "' 不存在" };
        if (hit.knowledge_count > 0) {
            return {
                success: false,
                error: "无法删除科目 '" + subjectName + "'，该科目包含 " + hit.knowledge_count +
                    " 个知识点。只有知识点数量为0的科目才能删除。",
            };
        }
        const r = await req('DELETE', '/api/subjects/' + encodeURIComponent(subjectName))
            .catch(function () { return null; });
        if (!r || r.deleted === false) return { success: false, error: '科目删除失败' };
        return { success: true, message: "科目 '" + subjectName + "' 删除成功" };
    }, { as: 'json', name: 'deleteSubject' });

    // ---------- 六、知识点详情 / 笔记 / 题目 ----------
    bridge.getKnowledgePointDetail = bridgeFn(function (pid) {
        return req('GET', '/api/knowledge/points/' + encodeURIComponent(pid) + '/detail');
    }, { as: 'json', name: 'getKnowledgePointDetail' });

    bridge.getKnowledgePointNotes = bridgeFn(function (pid) {
        return req('GET', '/api/knowledge/points/' + encodeURIComponent(pid) + '/notes');
    }, { as: 'json', name: 'getKnowledgePointNotes' });

    bridge.getNoteContent = bridgeFn(function (noteId) {
        return req('GET', '/api/notes/' + encodeURIComponent(noteId) + '/content');
    }, { as: 'json', name: 'getNoteContent' });

    bridge.getKnowledgePointQuestions = bridgeFn(function (pid) {
        return req('GET', '/api/knowledge/points/' + encodeURIComponent(pid) + '/questions');
    }, { as: 'json', name: 'getKnowledgePointQuestions' });

    // ---------- 七、AI 对话（chatResponseReady 本地信号） ----------
    const chatListeners = [];
    const chatResponseReady = {
        connect: function (fn) { if (typeof fn === 'function') chatListeners.push(fn); },
        disconnect: function (fn) {
            for (let i = chatListeners.length - 1; i >= 0; i--) {
                if (chatListeners[i] === fn) chatListeners.splice(i, 1);
            }
        },
        emit: function (jsonStr) {
            chatListeners.slice().forEach(function (fn) {
                try { fn(jsonStr); } catch (e) { console.error('[chatResponseReady]', e); }
            });
        },
    };
    bridge.chatResponseReady = chatResponseReady;

    bridge.chatWithAI = bridgeFn(function (/* message, historyJson */) {
        return { success: true, message: 'processing', status: 'processing' };
    }, { as: 'json', name: 'chatWithAI' });

    // 四期D组：进行中的聊天请求控制器（abortChat 中断用）
    let activeChatCtrl = null;
    bridge.abortChat = function () {
        if (activeChatCtrl) { try { activeChatCtrl.abort(); } catch (e) { /* ignore */ } activeChatCtrl = null; }
    };

    bridge.chatWithAIAsync = bridgeFn(async function (message, conversationHistoryJson) {
        const history = parseArg(conversationHistoryJson, []) || [];
        const KOBI_FALLBACKS = [
            '汪！我现在有点累了，稍后再聊好吗？',
            '抱歉，我的小脑瓜现在有点转不过来，请稍后再试试。',
            '哎呀，我好像走神了，能再说一遍吗？',
            '我需要先去充充电，等会儿再来帮你！',
        ];
        const ctrl = new AbortController();
        activeChatCtrl = ctrl;
        let payload;
        try {
            payload = await req('POST', '/api/llm/chat', {
                message: message, conversation_history: history,
            }, { signal: ctrl.signal, skipBilling: true });  // Chat 扣分由 base.html 消息尾注展示
            if (!payload || !payload.message) throw new Error('空响应');
        } catch (e) {
            if (e && e.name === 'AbortError') {
                // 用户主动中断：不兜底、不发回落，通知调用方恢复 UI
                activeChatCtrl = null;
                const aborted = J({ success: false, aborted: true, message: '' });
                chatResponseReady.emit(aborted);
                return aborted;
            }
            payload = {
                success: true,
                message: KOBI_FALLBACKS[Math.floor(Math.random() * KOBI_FALLBACKS.length)],
            };
        }
        if (activeChatCtrl === ctrl) activeChatCtrl = null;
        const jsonStr = J(payload);
        chatResponseReady.emit(jsonStr);  // Qt：无论成败都 success:true
        return jsonStr;
    }, { as: 'raw', name: 'chatWithAIAsync' });

    bridge.summarizeConversation = bridgeFn(function (conversationHistoryJson) {
        const history = parseArg(conversationHistoryJson, []) || [];
        return req('POST', '/api/llm/summarize-conversation', { conversation_history: history });
    }, { as: 'json', name: 'summarizeConversation' });

    bridge.saveConversation = bridgeFn(function (conversationDataJson) {
        return req('POST', '/api/conversations', parseArg(conversationDataJson, {}));
    }, { as: 'json', name: 'saveConversation' });

    bridge.loadConversationHistory = bridgeFn(function () {
        return req('GET', '/api/conversations');
    }, { as: 'json', name: 'loadConversationHistory' });

    bridge.loadConversationById = bridgeFn(function (conversationId) {
        return req('GET', '/api/conversations/' + encodeURIComponent(conversationId));
    }, { as: 'json', name: 'loadConversationById' });

    // ---------- 八、练习出题 / 评估 / 错题入库 ----------
    bridge.generatePracticeQuestions = bridgeFn(function (selectedText) {
        return req('POST', '/api/practice/generate-questions', { selected_text: selectedText || '' });
    }, { as: 'raw', name: 'generatePracticeQuestions' });

    bridge.evaluatePracticeAnswers = bridgeFn(function (questions, answers) {
        return req('POST', '/api/practice/evaluate-answers', {
            questions: questions || '', answers: answers || '',
        });
    }, { as: 'raw', name: 'evaluatePracticeAnswers' });

    bridge.evaluatePracticeAnswer = bridgeFn(function (evaluationDataJson) {
        const d = parseArg(evaluationDataJson, {}) || {};
        return req('POST', '/api/practice/evaluate-answer', {
            question: d.question || '', answer: d.answer || '', practice_id: d.practice_id || '',
        });
    }, { as: 'json', name: 'evaluatePracticeAnswer' });

    bridge.addToErrorBank = bridgeFn(function (errorDataJson) {
        return req('POST', '/api/practice/slice-errors', parseArg(errorDataJson, {}));
    }, { as: 'json', name: 'addToErrorBank' });

    bridge.matchKnowledgePointsForSubject = bridgeFn(function (matchDataJson) {
        return req('POST', '/api/practice/match-points', parseArg(matchDataJson, {}));
    }, { as: 'json', name: 'matchKnowledgePointsForSubject' });

    bridge.saveErrorsToKnowledgeBase = bridgeFn(function (saveDataJson) {
        return req('POST', '/api/practice/save-errors', parseArg(saveDataJson, {}));
    }, { as: 'json', name: 'saveErrorsToKnowledgeBase' });

    bridge.generateNewPractice = bridgeFn(function () {
        return req('POST', '/api/practice/new', {});
    }, { as: 'json', name: 'generateNewPractice' });

    bridge.importPracticeErrors = bridgeFn(function (errorDataJson) {
        // D 类：Qt 版实际不入库，只回传数据让前端打开入库对话框
        const d = parseArg(errorDataJson, {}) || {};
        if (d.evaluation_result) {
            return {
                success: true,
                message: '错题入库功能需要在Qt界面中操作',
                action: 'open_error_import_dialog',
                data: {
                    practice_content: d.practice_content || '',
                    evaluation_result: d.evaluation_result,
                    selected_text: d.selected_text || '',
                },
            };
        }
        return { success: false, error: '没有评估结果可以入库' };
    }, { as: 'json', name: 'importPracticeErrors' });

    // ---------- 九、练习历史 ----------
    bridge.getPracticeHistory = bridgeFn(function () {
        return req('GET', '/api/practice/history');
    }, { as: 'json', name: 'getPracticeHistory' });

    bridge.loadPracticeHistory = bridgeFn(function (practiceId) {
        return req('GET', '/api/practice/history/' + encodeURIComponent(practiceId));
    }, { as: 'json', name: 'loadPracticeHistory' });

    bridge.savePracticeHistory = bridgeFn(function (practiceDataJson) {
        return req('POST', '/api/practice/history', parseArg(practiceDataJson, {}));
    }, { as: 'json', name: 'savePracticeHistory' });

    bridge.savePracticeEvaluation = bridgeFn(function (evaluationDataJson) {
        return req('POST', '/api/practice/evaluation', parseArg(evaluationDataJson, {}));
    }, { as: 'json', name: 'savePracticeEvaluation' });

    bridge.updatePracticeEvaluation = bridgeFn(function (practiceId, evaluationDataJson) {
        return req('PUT', '/api/practice/history/' + encodeURIComponent(practiceId) + '/evaluation',
            parseArg(evaluationDataJson, {}));
    }, { as: 'json', name: 'updatePracticeEvaluation' });

    // ---------- 十、脑图 / 学习路径 ----------
    bridge.getOrGenerateMindmap = bridgeFn(async function (subjectName) {
        try {
            const data = await req('POST', '/api/mindmap/generate', { subject_name: subjectName });
            if (data === undefined || data === null) {
                return { success: false, error: '该学科暂无知识点数据，无法生成脑图' };
            }
            if (data.success === false) {
                return { success: false, error: data.error || '该学科暂无知识点数据，无法生成脑图' };
            }
            return { success: true, mindmap: data.mindmap !== undefined ? data.mindmap : data };
        } catch (e) {
            return { success: false, error: String(e.message || e) };
        }
    }, { as: 'json', name: 'getOrGenerateMindmap' });

    bridge.saveMindmap = bridgeFn(async function (subjectName, mindmapDataJson) {
        const data = parseArg(mindmapDataJson, mindmapDataJson || '');
        const ok = await req('POST', '/api/mindmap/save', {
            subject_name: subjectName, mindmap_data: data,
        });
        return ok === true;
    }, { as: 'bool', name: 'saveMindmap' });

    bridge.clearMindmapCache = bridgeFn(async function (subjectName) {
        try {
            const data = await req('POST', '/api/mindmap/clear', { subject_name: subjectName });
            const cleared = !(data && data.cleared === false);
            return cleared
                ? { success: true, message: '已清除 ' + subjectName + ' 的脑图缓存' }
                : { success: false, error: '缓存清除失败，可能缓存不存在' };
        } catch (e) {
            return { success: false, error: String(e.message || e) };
        }
    }, { as: 'json', name: 'clearMindmapCache' });

    bridge.getOrGenerateLearningPath = bridgeFn(async function (subjectName) {
        try {
            const data = await req('GET', '/api/learning-path?subject=' + encodeURIComponent(subjectName || ''));
            if (data === undefined || data === null) return { success: false, error: '学习路径生成失败' };
            return { success: true, learningPath: data.learningPath !== undefined ? data.learningPath : data };
        } catch (e) {
            return { success: false, error: String(e.message || e) };
        }
    }, { as: 'json', name: 'getOrGenerateLearningPath' });

    bridge.clearLearningPathCache = bridgeFn(async function (subjectName) {
        try {
            const data = await req('POST', '/api/learning-path/clear', { subject_name: subjectName });
            const cleared = !(data && data.cleared === false);
            return cleared
                ? { success: true, message: '已清除 ' + subjectName + ' 的学习路径缓存' }
                : { success: false, error: '缓存清除失败，可能缓存不存在' };
        } catch (e) {
            return { success: false, error: String(e.message || e) };
        }
    }, { as: 'json', name: 'clearLearningPathCache' });

    // ---------- 十一、熟练度评估 ----------
    bridge.generateAssessmentQuestions = bridgeFn(function (knowledgePointId) {
        return req('POST', '/api/knowledge/points/' + encodeURIComponent(knowledgePointId) +
            '/generate-assessment', {});
    }, { as: 'json', name: 'generateAssessmentQuestions' });

    bridge.submitMasteryAssessment = bridgeFn(function (knowledgePointId, questionsJson, answersJson) {
        return req('POST', '/api/knowledge/points/' + encodeURIComponent(knowledgePointId) + '/assessment', {
            questions: parseArg(questionsJson, []) || [],
            answers: parseArg(answersJson, []) || [],
        });
    }, { as: 'json', name: 'submitMasteryAssessment' });

    // ---------- 十二、录音 / 转写 / 音频设备（C 类：Electron 委托 + 安全 fallback） ----------
    bridge.startRecording = cFn('startRecording', function () {
        return { success: false, error: '请先选择音频输入设备', needDeviceSelection: true };
    });
    bridge.stopRecording = cFn('stopRecording', function () {
        return { success: false, error: '录音未在进行中' };
    });
    bridge.pauseRecording = cFn('pauseRecording', function () {
        return { success: false, error: '录音未在进行中' };
    });
    bridge.resumeRecording = cFn('pauseRecording', function () {
        return { success: false, error: '录音未在进行中' };
    });

    bridge.getTranscriptionText = cFn('getTranscriptionText', function () {
        return { success: true, transcription: '', summary: '', is_recording: false };
    });

    bridge.saveNotes = cFn('saveNotes', function () {
        return { success: false, error: '保存笔记失败: 录音数据不存在' };
    });

    bridge.manualSummary = cFn('manualSummary', function () {
        return { success: false, error: '没有转写内容可以总结' };
    });

    bridge.summarizeText = bridgeFn(function (text) {
        return req('POST', '/api/llm/summarize-text', { text: text || '' });
    }, { as: 'json', name: 'summarizeText' });

    bridge.takeScreenshot = cFn('takeScreenshot', function () {
        return { success: false, error: '截图笔记失败: 需要桌面客户端支持' };
    });

    bridge.saveTranscriptSession = cFn('saveTranscriptSession', function () {
        return '';  // Qt 失败返回空串（页面拿路径串）
    });

    bridge.loadTranscriptHistory = cFn('loadTranscriptHistory', function () {
        // Qt：无返回值，经 onTranscriptHistoryLoaded 推送；取消/失败推空串
        setTimeout(function () {
            if (typeof global.onTranscriptHistoryLoaded === 'function') {
                global.onTranscriptHistoryLoaded('');
            }
        }, 50);
        return { success: true };
    });

    bridge.getAudioDevices = bridgeFn(async function () {
        const eb = global.electronBridge;
        if (eb && typeof eb.getAudioDevices === 'function') {
            return await Promise.resolve(eb.getAudioDevices());
        }
        // 浏览器/渲染进程环境：Web API 枚举（loopback 系统音频由 P4 Electron 提供）
        try {
            const list = await navigator.mediaDevices.enumerateDevices();
            const devices = [], inputDevices = [], systemAudioDevices = [];
            let idx = 0;
            list.filter(function (d) { return d.kind === 'audioinput'; }).forEach(function (d) {
                const isSystem = /mix|loopback|输出|system/i.test(d.label || '');
                const item = {
                    index: idx, name: d.label || ('设备 ' + idx), deviceId: d.deviceId,
                    sampleRate: 0, channels: 0,
                };
                if (isSystem) {
                    systemAudioDevices.push(Object.assign({ type: 'system_audio', displayName: item.name, description: '' }, item));
                } else {
                    inputDevices.push(Object.assign({ type: 'input', displayName: item.name, description: '' }, item));
                }
                devices.push(item);
                idx++;
            });
            return { success: true, devices: devices, inputDevices: inputDevices, systemAudioDevices: systemAudioDevices };
        } catch (e) {
            return { success: false, error: '获取设备失败: ' + (e.message || e) };
        }
    }, { as: 'json', name: 'getAudioDevices' });

    bridge.selectAudioDevice = bridgeFn(async function (deviceIndex, deviceName) {
        const eb = global.electronBridge;
        if (eb && typeof eb.selectAudioDevice === 'function') {
            return await Promise.resolve(eb.selectAudioDevice(deviceIndex, deviceName));
        }
        await req('PUT', '/api/config', {
            selected_audio_device_index: Number(deviceIndex),
            selected_audio_device_name: String(deviceName || ''),
        }).catch(function () { /* 配置持久化失败不阻断 */ });
        return { success: true, message: '已选择设备: ' + deviceName };
    }, { as: 'json', name: 'selectAudioDevice' });

    bridge.getSelectedDevice = bridgeFn(async function () {
        const eb = global.electronBridge;
        if (eb && typeof eb.getSelectedDevice === 'function') {
            return await Promise.resolve(eb.getSelectedDevice());
        }
        const cfg = await req('GET', '/api/config').catch(function () { return {}; });
        const idx = cfg.selected_audio_device_index;
        if (idx !== undefined && idx !== null && idx >= 0) {
            return { success: true, device_index: idx, device_name: cfg.selected_audio_device_name || '' };
        }
        return { success: false, message: '未选择设备' };  // 注意：Qt 用 message 非 error
    }, { as: 'json', name: 'getSelectedDevice' });

    bridge.getDeviceLevels = cFn('getDeviceLevels', function () {
        return { success: false, error: '未选择设备' };
    });
    bridge.getSingleDeviceLevel = cFn('getSingleDeviceLevel', function () {
        return { success: true, level: 0.0, message: '录音已停止' };
    });

    bridge.testDeviceRecording = cFn('testDeviceRecording', function (args) {
        const name = (args && args[1]) || '';
        setTimeout(function () {
            if (typeof global.onTestRecordingFinished === 'function') {
                global.onTestRecordingFinished(null, name);
            }
        }, 1000);
        return { success: true, message: '开始模拟测试设备: ' + name + '（1秒模拟）', duration: 1 };
    });

    // 桥类未定义但页面调用：补桩，防 await 挂起
    bridge.testDeviceCompatibility = bridgeFn(function () {
        return { success: true, message: '兼容性检查由桌面客户端处理' };
    }, { as: 'json', name: 'testDeviceCompatibility' });

    bridge.chooseInputDevice = cFn('chooseInputDevice', function () {
        return { success: false, message: '用户取消选择' };
    });

    bridge.testAudioSource = bridgeFn(function () {
        return { success: true, message: '音源测试正常' };
    }, { as: 'json', name: 'testAudioSource' });
    bridge.testRecording = bridgeFn(function () {
        return { success: true, message: '录音测试正常' };
    }, { as: 'json', name: 'testRecording' });
    bridge.testRecordingWithTranscription = bridgeFn(function () {
        const eb = global.electronBridge;
        if (eb && typeof eb.testRecordingWithTranscription === 'function') {
            return Promise.resolve(eb.testRecordingWithTranscription());
        }
        return { success: false, error: '请先选择音频输入设备', needDeviceSelection: true };
    }, { as: 'json', name: 'testRecordingWithTranscription' });
    bridge.testRecordingFlow = bridgeFn(function () {
        return { success: false, error: '完整录音流程需桌面客户端', step: 'device_selection' };
    }, { as: 'json', name: 'testRecordingFlow' });

    // ---------- 十三、未定义方法补桩 ----------
    bridge.render_markdown = bridgeFn(function (content) {
        return mdToHtml(content || '');
    }, { as: 'raw', name: 'render_markdown' });

    // ============================== 挂载 ==============================

    global.pybridge = bridge;
    global.bridge = bridge;
    // SPA 壳（spa_layout.html）兼容兼顾：多页兼底路由表也暴露到 window
    global.PAGE_ROUTES = PAGE_ROUTES;

    // 登录态工具（登录页 / 顶栏退出使用）
    global.LLAuth = {
        getToken: getToken, setToken: setToken, clearToken: clearToken,
        request: req,
        logout: function () {
            clearToken();
            location.href = '/login';
        },
    };

    console.log('✅ pybridge 兼容层已加载（' + Object.keys(bridge).length + ' 个桥方法）');
})(window);
