/* NoteVditor：Vditor Markdown 编辑器公共桥接模块（2026-10-08）
 * 来源：知识点描述编辑器已验证技术收敛（pm_pages.js descEd* 系列，CDP 16/16 断言全绿轮）。
 * 依赖：window.Vditor（本地 vendor /static/vendor/vditor，缺失时自动回退 textarea）、
 *       window.pybridge.getImageAsBase64（/api/vault/image 桥，编辑器内相对路径图片水合显示用）。
 * 关键约定（Vditor 4.0 实测，勿凭旧版文档改动）：
 *   - lang 必须下划线格式 'zh_CN'，传 'zh-CN' 构造函数直接抛 options.lang error；
 *   - 4.0 已移除 insertImage，插入图片一律走 insertMD('![](rel)')；
 *   - upload.handler 拦截粘贴/拖入，自定义上传完成后必须手动复位 vd.vditor.upload.isUploading；
 *   - 编辑器内图片 src 会被水合成 base64，取值前必须换回原路径（防 base64 入库），见 getValue。
 * 用法：
 *   var ed = NoteVditor.create(mountEl, {
 *     value, placeholder, height,                 // height: 数字 或 'auto'（撑满容器）
 *     toolbar: [...],                             // 缺省用本模块默认工具栏
 *     resolveImg: function(src){ return path; },  // 相对路径→可送 getImageAsBase64 的串；返回 null 不水合
 *     onUploadFile: function(file, cb){ cb(err, relPath); }, // 保存粘贴/拖入的图片，回 rel 入库引用
 *     onInput: fn(), onReady: fn(), onNotice: fn(msg, isErr)
 *   });
 *   ed.getValue() / ed.setValue(md) / ed.insertMD(md) / ed.focus() / ed.isFallback() / ed.destroy()
 */
(function () {
    'use strict';

    // 「加载中…」占位图（与知识点页同款 SVG 占位，水合期间防破图图标）
    var IMG_PH = 'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMjAwIiBoZWlnaHQ9IjEwMCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cmVjdCB3aWR0aD0iMTAwJSIgaGVpZ2h0PSIxMDAlIiBmaWxsPSIjZjBmMGYwIi8+PHRleHQgeD0iNTAlIiB5PSI1MCUiIGZvbnQtZmFtaWx5PSJBcmlhbCIgZm9udC1zaXplPSIxNCIgZmlsbD0iIzk5OSIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZHk9Ii4zZW0iPuWKoOi9veS4rS4uLjwvdGV4dD48L3N2Zz4=';

    var DEFAULT_TOOLBAR = ['headings', 'bold', 'italic', 'strike', '|', 'list', 'ordered-list', 'check', 'quote', 'code', 'inline-code', 'link', 'table', 'line', '|', 'undo', 'redo'];

    function create(mountEl, o) {
        o = o || {};
        if (!mountEl) return null;

        // —— 回退通道：Vditor 脚本缺失时用等价 textarea，功能不中断（核心功能降级兜底规范） ——
        if (!window.Vditor) {
            var ta = document.createElement('textarea');
            ta.rows = 12;
            ta.style.width = '100%';
            ta.style.height = '100%'; // 撑满宿主容器，与 Vditor 正路径（height:'100%'）行为对齐
            ta.placeholder = o.placeholder || 'Markdown 内容（编辑器组件未加载，已回退纯文本模式，暂不支持贴图）';
            if (o.textareaClass) ta.className = o.textareaClass;
            ta.value = o.value || '';
            ta.addEventListener('input', function () { if (o.onInput) o.onInput(); });
            mountEl.appendChild(ta);
            if (o.onReady) setTimeout(o.onReady, 0);
            return {
                mode: 'textarea', mount: mountEl, ta: ta,
                getValue: function () { return ta.value; },
                setValue: function (t) { ta.value = t || ''; },
                insertMD: function (t) { ta.value += (ta.value && !/\n$/.test(ta.value) ? '\n\n' : '') + t; },
                focus: function () { ta.focus(); },
                isReady: function () { return true; },
                isFallback: function () { return true; },
                destroy: function () { ta.remove(); }
            };
        }

        // ready 前的 setValue/insertMD 入 pending 队列，after() 里按序冲刷。
        // 根因：Vditor 初始化异步，after 前 vd.setValue 会被吞而 vd.insertMD 却生效，
        // 去抖 input 把“只剩插入片段”的内容镜像回数据层 → 丢正文（2026-10-08 学页冒烟实测）。
        var api = { mode: 'vditor', mount: mountEl, vd: null, obs: null, ready: false, pendingValue: null, pendingInserts: [] };
        var hydrate = function () { hydrateImgs(api.mount, o); };

        var vd = new window.Vditor(mountEl, {
            cdn: '/static/vendor/vditor',
            mode: 'ir',
            // Vditor 4.0 校验白名单为下划线格式（zh_CN），传 zh-CN 会在构造函数直接抛 options.lang error
            lang: 'zh_CN',
            icon: 'material',
            height: o.height === 'auto' ? 'auto' : (o.height || 320),
            value: o.value || '',
            placeholder: o.placeholder || '支持 Markdown 语法；截图可直接 Ctrl+V 粘贴或拖入',
            cache: { enable: false },
            toolbarConfig: { pin: true },
            toolbar: o.toolbar || DEFAULT_TOOLBAR,
            preview: {
                hljs: { style: 'github', lineNumber: false },
                // KaTeX 引擎（2026-10-13 启用）：vendor 已补齐 dist/js/katex/{katex.min.css,katex.min.js,mhchem.min.js,fonts/}
                // 本地落盘（Vditor 硬编码拉取 {cdn}/dist/js/katex/*，缺文件时 404+pageerror，故当初置 none；
                // 现文件齐备可开回），编辑弹窗内 $…$/$$…$$ 公式即时渲染；降级仍由 textarea 回退通道保底。
                math: { engine: 'KaTeX' }
            },
            input: function () { if (o.onInput) o.onInput(); },
            upload: {
                accept: 'image/*',
                handler: function (files) {
                    // 多文件并发：计数器归零才复位 isUploading，防首张完成即禁入失效
                    var left = files.length;
                    var oneDone = function () {
                        left--;
                        if (left <= 0) { try { vd.vditor.upload.isUploading = false; } catch (e) { /* noop */ } }
                    };
                    for (var i = 0; i < files.length; i++) uploadOne(files[i], oneDone);
                    return null; // 异步上传；错误已经 onNotice 呈现
                }
            },
            after: function () {
                api.ready = true;
                // 冲刷 pending：先整体 setValue 再按序 insertMD，保证顺位与调用序一致
                try {
                    if (api.pendingValue !== null) { vd.setValue(api.pendingValue || ''); api.pendingValue = null; }
                    api.pendingInserts.forEach(function (t) { try { vd.insertMD(t); } catch (e) { /* noop */ } });
                } catch (e) { /* noop */ }
                api.pendingInserts = [];
                hydrate();
                if (o.onReady) o.onReady();
            }
        });
        api.vd = vd;
        mountEl.__vd = vd; // 调试/CDP 断言入口：Vditor 4 不挂 window.vditor，实例留挂载体上

        function uploadOne(file, done) {
            var finish = function () { if (done) done(); else { try { vd.vditor.upload.isUploading = false; } catch (e) { /* noop */ } } };
            if (!file || !/^image\//i.test(file.type || '')) { notice('仅支持粘贴/插入图片', true); finish(); return; }
            if (!o.onUploadFile) { notice('贴图功能未启用', true); finish(); return; }
            var fr = new FileReader();
            fr.onload = function () {
                o.onUploadFile(file, function (err, rel) {
                    try {
                        if (err || !rel) { notice('图片插入失败：' + ((err && err.message) || '保存失败'), true); return; }
                        try { vd.insertMD('![图片](' + rel + ')'); } catch (e) { /* noop */ }
                        notice('图片已插入');
                    } finally { finish(); }
                });
            };
            fr.onerror = function () { notice('读取图片数据失败', true); finish(); };
            fr.readAsDataURL(file);
        }
        function notice(msg, isErr) { if (o.onNotice) o.onNotice(msg, isErr); }

        // 持续覆盖 Vditor 重渲染：观察器监听挂载区，新出现的 img 走水合
        if (window.MutationObserver) {
            api.obs = new MutationObserver(function () { hydrateImgs(api.mount, o); });
            api.obs.observe(mountEl, { childList: true, subtree: true, attributes: true, attributeFilter: ['src'] });
        }

        return {
            mode: 'vditor',
            mount: mountEl,
            isFallback: function () { return false; },
            isReady: function () { return api.ready; },
            focus: function () { try { vd.focus(); } catch (e) { /* noop */ } },
            insertMD: function (md) {
                if (!api.ready) { api.pendingInserts.push(md); return; }
                try { vd.insertMD(md); } catch (e) { /* noop */ }
            },
            setValue: function (t) {
                if (!api.ready) { api.pendingValue = t || ''; api.pendingInserts = []; return; }
                try { vd.setValue(t || ''); } catch (e) { /* noop */ }
            },
            // 取编辑器 MD：先把水合过的 base64 换回原始路径再 getValue，保证入库的是引用而非巨串；
            // 读完后同 tick 立即换回 base64 保持显示（观察器 data-vd-hy 短路不会自动补回）
            getValue: function () {
                var restore = [];
                api.mount.querySelectorAll('img[data-vd-src]').forEach(function (im) {
                    var cur = im.getAttribute('src') || '';
                    if (/^data:/i.test(cur)) {
                        restore.push([im, cur]);
                        im.setAttribute('src', im.getAttribute('data-vd-src'));
                    }
                });
                var md = '';
                try { md = vd.getValue() || ''; } catch (e) { md = ''; }
                restore.forEach(function (p) { try { p[0].setAttribute('src', p[1]); } catch (e) { /* noop */ } });
                return md;
            },
            destroy: function () {
                try { if (api.obs) api.obs.disconnect(); } catch (e) { /* noop */ }
                api.obs = null;
                try { vd.destroy(); } catch (e) { /* noop */ }
                api.mount.innerHTML = '';
            }
        };
    }

    // 编辑区内图片（相对路径浏览器无法直载）换 base64 显示；data-vd-hy 防重复请求，data-vd-src 存原引用
    function hydrateImgs(mount, o) {
        if (!mount || !window.pybridge || !window.pybridge.getImageAsBase64) return;
        mount.querySelectorAll('img').forEach(function (img) {
            var src = img.getAttribute('src') || '';
            if (!src || img.getAttribute('data-vd-hy')) return;
            img.setAttribute('data-vd-hy', '1');
            if (/^(data:|blob:|https?:)/i.test(src)) return; // base64/外链保持原样
            var p = src;
            try { p = decodeURIComponent(src); } catch (e) { /* 非法编码保留原串 */ }
            if (o.resolveImg) {
                try { p = o.resolveImg(p); } catch (e) { p = null; }
            }
            if (!p) return;
            img.setAttribute('data-vd-src', src);
            img.setAttribute('src', IMG_PH);
            window.pybridge.getImageAsBase64(p, function (result) {
                try {
                    var resp = JSON.parse(result);
                    if (!mount.contains(img)) return; // 已销毁/重建 → 旧回包丢弃
                    if (resp.success && resp.dataUrl) {
                        img.setAttribute('src', resp.dataUrl);
                        img.setAttribute('title', '图片: ' + p);
                    } else {
                        img.setAttribute('alt', '图片加载失败: ' + p);
                    }
                } catch (e) { /* 解析失败保持占位 */ }
            });
        });
    }

    window.NoteVditor = { create: create };
})();
