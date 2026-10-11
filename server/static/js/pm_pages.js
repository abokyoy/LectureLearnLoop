/**
 * 练/记 四页共享模块（批4：假数据全面下线，全部走真实 API + 空态）
 * 页面骨架通过 <div data-pm-page="practice_knowledge|practice_errors|memory_knowledge|memory_errors"> 声明，
 * 本文件由片段模板以 <script src> 引入，加载后自动扫描并初始化对应页面。
 * 数据源：/api/subjects、/api/knowledge/points、/api/kb/errors、/api/kb/errors/<id>/reviewed、/api/dashboard/stats
 * c2（2026-10-01）：记系列全卡片形态 —— 知识点/错题翻卡背面四档自评走 /api/kb/<kind>/<id>/rate（FSRS 内核）。
 */
(function (global) {
    'use strict';

    var SPRITE = '/static/icons/lucide-sprite.svg';

    // ---------------- 公共工具（与 dashboard 页内联脚本同口径，收敛到本模块复用） ----------------
    function tk() { return (global.llGetToken ? global.llGetToken() : (localStorage.getItem('ll_token') || sessionStorage.getItem('ll_token') || '')); }
    function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
    function relTime(ts) {
        try {
            var t = new Date(String(ts).replace(' ', 'T') + 'Z'); // 库内为 UTC
            var d = Date.now() - t.getTime();
            if (!isFinite(d)) return String(ts || ''); // Invalid Date（null/脏时间戳）不显示 NaN
            if (d < 0) d = 0;
            var m = Math.floor(d / 60000);
            if (m < 1) return '刚刚';
            if (m < 60) return m + ' 分钟前';
            var h = Math.floor(m / 60);
            if (h < 24) return h + ' 小时前';
            return Math.floor(h / 24) + ' 天前';
        } catch (e) { return String(ts || ''); }
    }
    function icon(name, cls) {
        return '<svg class="' + (cls || 'w-4 h-4') + '" aria-hidden="true"><use href="' + SPRITE + '#li-' + name + '"/></svg>';
    }
    function getJSON(url) {
        return fetch(url, { headers: { 'Authorization': 'Bearer ' + tk() } })
            .then(function (r) { return r.json(); })
            .then(function (j) { if (!j || !j.success) throw new Error((j && j.error) || '请求失败'); return j.data; });
    }
    function postJSON(url, body) {
        return fetch(url, {
            method: 'POST',
            headers: { 'Authorization': 'Bearer ' + tk(), 'Content-Type': 'application/json' },
            body: JSON.stringify(body || {})
        }).then(function (r) { return r.json(); })
            .then(function (j) { if (!j || !j.success) throw new Error((j && j.error) || '请求失败'); return j.data; });
    }
    // P3 描述编辑：PUT 通道（与 postJSON 同双层契约/鉴权口径）
    function sendJSON(method, url, body) {
        return fetch(url, {
            method: method,
            headers: { 'Authorization': 'Bearer ' + tk(), 'Content-Type': 'application/json' },
            body: JSON.stringify(body || {})
        }).then(function (r) { return r.json(); })
            .then(function (j) { if (!j || !j.success) throw new Error((j && j.error) || '请求失败'); return j.data; });
    }
    function goMenu(cid) { if (typeof global.handleMenuClick === 'function') global.handleMenuClick(cid); }
    // u10：直达知识点详情页（不再先跳脑图再弹层——用户明确否定的路径）。
    // 旗标 pm_pending_point 由本页渲染器 bootKnowledgePoint 消费；脑图页内点节点弹层行为保持不变。
    function goPracticePoint(id, name) {
        // CodeReview 批9c M-1：旗标带时间戳，导航被取消/中断时陈旧旗标在消费端过期丢弃，不会幽灵弹出
        try { localStorage.setItem('pm_pending_point', JSON.stringify({ id: String(id), name: String(name || ''), ts: Date.now() })); } catch (e) { /* ignore */ }
        goMenu('knowledge_point');
    }
    // 错题翻卡直达旗标：总览「推荐复习错题·去复习」→ 记错题页卡片模式从该卡开始（消费端 10s 过期，同上口径）
    function goReviewError(subject, eid) {
        try { localStorage.setItem('pm_pending_review', JSON.stringify({ subject: String(subject || ''), eid: String(eid || ''), ts: Date.now() })); } catch (e) { /* ignore */ }
        goMenu('memory_errors');
    }
    function truncate(s, n) { s = String(s || ''); return s.length > n ? s.slice(0, n) + '…' : s; }
    // mastery_score = -1 是“未评估”哨兵值（建点默认入库），禁止当 0% 展示或参与均值（批5 负数 bug 根因）
    function isUnrated(score) { return score == null || Number(score) < 0; }
    function masteryBadge(score) {
        if (isUnrated(score)) return '<span class="cl-badge bg-cl-bg text-cl-text-3">未评估</span>';
        var v = Math.max(0, Math.min(100, Number(score) || 0));
        var cls = v >= 80 ? 'bg-cl-secondary-soft text-cl-secondary' : 'bg-cl-primary-soft text-cl-primary';
        return '<span class="cl-badge ' + cls + '">掌握 ' + v + '%</span>';
    }
    function progressBar(score) {
        var v = isUnrated(score) ? 0 : Math.max(0, Math.min(100, Number(score) || 0));
        return '<div class="cl-progress"><div class="cl-progress-bar" style="width:' + v + '%"></div></div>';
    }

    // ---------------- 空态 ----------------
    function emptyBox(title, sub, btnText, btnGo) {
        return '<div class="cl-empty">' + icon('dog', 'w-10 h-10 text-cl-text-3')
            + '<p class="font-medium">' + esc(title) + '</p>'
            + (sub ? '<p class="text-xs text-cl-text-3">' + esc(sub) + '</p>' : '')
            + (btnText ? '<button class="cl-btn-ghost !h-9 !text-xs" data-go="' + esc(btnGo) + '">' + esc(btnText) + '</button>' : '')
            + '</div>';
    }
    function bindGoLinks(root) {
        root.querySelectorAll('[data-go]').forEach(function (b) {
            // u8 CodeReview MINOR：静态入口卡会被先绑一次，渲染后重绑需去重，防同拍双导航
            if (b.__goBound) return; b.__goBound = true;
            b.addEventListener('click', function () { goMenu(b.getAttribute('data-go')); });
        });
        // 批9：带知识点的直达按钮（去练习/巩固）
        root.querySelectorAll('[data-gopoint]').forEach(function (b) {
            if (b.__goBound) return; b.__goBound = true;
            b.addEventListener('click', function () { goPracticePoint(b.getAttribute('data-gopoint'), b.getAttribute('data-goname')); });
        });
        // 错题翻卡：总览推荐复习「去复习」直达记错题页卡片模式对应卡
        root.querySelectorAll('[data-gorev]').forEach(function (b) {
            if (b.__goBound) return; b.__goBound = true;
            b.addEventListener('click', function () { goReviewError(b.getAttribute('data-gorevsubj'), b.getAttribute('data-gorev')); });
        });
    }

    // ---------------- 错题题目展示公共渲染（列表详情与翻卡背面复用） ----------------
    var QUESTION_TYPE_NAMES = { single: '单选题', judge: '判断题', fill: '填空题', short: '简答题' };
    // 选项列表：markCorrect=true 时高亮正确项。字母按索引派生（A+idx，与答题页/落库判分同契约），
    // 文本相等仅作兑底（防御存量异常数据）；无选项的存量旧题/判断题返回空串。
    // 2026-10-08 扩展（用户要求：判分结果页须显示原题选项）：可选第三参 userLetter
    // 标注用户误选项（红色 +「你选的」），不传时行为与旧版完全一致（错题列表/翻卡不受影响）。
    function optionsHtml(e, markCorrect, userLetter) {
        if (!e || !e.options || !e.options.length) return '';
        var correctLetter = String(e.correct_answer || '').trim().slice(0, 1).toUpperCase();
        var correctText = String(e.correct_answer || '').trim();
        var ul = String(userLetter || '').trim().slice(0, 1).toUpperCase();
        var userText = String(userLetter || '').trim();
        // 评审 Minor-2 守卫：仅当答案落在合法选项字母范围或选项文本相等时才算误选
        // （与 isAns 文本兑底同口径；防御填空/简答首字符巧合误标，并支持判断题文本答案）
        var validLetters = e.options.map(function (_, i) { return String.fromCharCode(65 + i); });
        return '<div class="mt-3 space-y-1.5">' + e.options.map(function (o, idx) {
            var letter = String.fromCharCode(65 + idx);
            var isAns = markCorrect && (letter === correctLetter || (correctText !== '' && String(o).trim() === correctText));
            var isUserPick = markCorrect && ((validLetters.indexOf(ul) >= 0 && letter === ul)
                || (userText !== '' && String(o).trim() === userText));
            var isUserWrong = isUserPick && !isAns;
            return '<div class="rounded-clbtn px-3 py-2 text-[13px] leading-relaxed ' + (isAns ? 'bg-cl-secondary-soft text-cl-secondary font-medium' : isUserWrong ? 'bg-cl-danger-soft text-cl-danger' : 'bg-cl-bg text-cl-text-2') + '">' + letter + '. ' + mdqHtml(o, '', true)
                + (isAns ? ' ' + icon('check', 'w-3.5 h-3.5 inline -mt-0.5') : '')
                + (isUserWrong ? ' <span class="ml-1 text-[11px] font-medium">（你选的）</span>' : '') + '</div>';
        }).join('') + '</div>';
    }
    // 翻卡 3D 样式（片段式注入一次，记错题/记知识点卡片模式共用；c2 起含四档自评条）
    function ensureFlipCss() {
        if (document.getElementById('pm-flip-css')) return;
        var st = document.createElement('style');
        st.id = 'pm-flip-css';
        // cl.css 为预编译产物（无 bg-red-100 等未扫描类），四档色条走自定义 CSS（integ 同款色语义）
        st.textContent = '.pm-flip-scene{perspective:1400px;height:58vh;min-height:380px}'
            + '.pm-flip-card{position:relative;width:100%;height:100%;transform-style:preserve-3d;transition:transform .5s;cursor:pointer}'
            + '.pm-flip-card.is-flipped{transform:rotateY(180deg)}'
            + '.pm-flip-face{position:absolute;inset:0;backface-visibility:hidden;-webkit-backface-visibility:hidden;overflow-y:auto}'
            + '.pm-flip-back{transform:rotateY(180deg)}'
            + '.pm-ratebar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:14px}'
            + '.pm-rate-btn{height:34px;padding:0 14px;border-radius:10px;border:1px solid;font-size:12px;font-weight:600;cursor:pointer;transition:filter .15s,opacity .15s}'
            + '.pm-rate-btn:hover:not(:disabled){filter:brightness(.96)}'
            + '.pm-rate-btn:disabled{opacity:.45;cursor:default}'
            + '.pm-rate-btn[data-rate="not_at_all"]{color:#b91c1c;border-color:#fca5a5;background:#fef2f2}'
            + '.pm-rate-btn[data-rate="vague"]{color:#c2410c;border-color:#fdba74;background:#fff7ed}'
            + '.pm-rate-btn[data-rate="familiar"]{color:#1d4ed8;border-color:#93c5fd;background:#eff6ff}'
            + '.pm-rate-btn[data-rate="perfect"]{color:#15803d;border-color:#86efac;background:#f0fdf4}';
        document.head.appendChild(st);
    }

    // ---------------- c2：翻卡四档自评（记知识点/记错题共用，走 /api/kb/<kind>/<id>/rate） ----------------
    var CARD_RATINGS = [
        { key: 'not_at_all', label: '很不熟悉' },
        { key: 'vague', label: '不熟悉' },
        { key: 'familiar', label: '熟悉' },
        { key: 'perfect', label: '非常熟悉' }
    ];
    function rateBarHtml(tip) {
        return '<div class="pm-ratebar">'
            + '<p class="w-full text-[11px] text-cl-text-3">' + esc(tip) + '</p>'
            + CARD_RATINGS.map(function (r) {
                return '<button class="pm-rate-btn" data-rate="' + r.key + '">' + esc(r.label) + '</button>';
            }).join('') + '</div>';
    }
    function bindRateBar(scope, onRate) {
        scope.querySelectorAll('[data-rate]').forEach(function (btn) {
            btn.addEventListener('click', function () { onRate(btn.getAttribute('data-rate'), btn); });
        });
    }

    // ---------------- c3：记忆数据面板（曲线+双星+手动熟练度；详情页/两记页共用，依赖 widgets.js） ----------------
    var FSR_STATE_NAMES = ['新学', '学习中（本回合翻卡）', '复习期（保持中）', '再学习（退化巩固）'];
    function memoryPanelHtml() {
        return '<div class="cl-section-title mb-3">' + icon('chart-column', 'w-4 h-4 text-cl-primary') + ' 记忆数据</div>'
            // 评审 c3 Minor-2：sm:grid-cols-2 未被 cl.css 预编译扫描，改用已扫描的 flex 族
            + '<div class="flex flex-wrap gap-x-8 gap-y-4">'
            + '<div><p class="text-[11px] text-cl-text-3 mb-1">难度星值</p><span data-mw="diff"></span></div>'
            + '<div><p class="text-[11px] text-cl-text-3 mb-1">重要度星值</p><span data-mw="imp"></span></div></div>'
            + '<div class="mt-4"><p class="text-[11px] text-cl-text-3 mb-1">熟练度（手动设定为最高优先，持续到下次真实复习）</p><div data-mw="slider"></div></div>'
            + '<div class="mt-4"><p class="text-[11px] text-cl-text-3 mb-1">熟练度曲线</p><div data-mw="curve" class="overflow-x-auto"></div></div>'
            + '<p class="text-[11px] text-cl-text-3 mt-3" data-mw="meta">加载中…</p>';
    }
    function mountMemoryWidgets(scope, kind, rid, onFail) {
        var root = scope.querySelector('[data-mw-root]') || scope;
        if (!root) return;
        if (!global.LLCurve || !global.LLStars || !global.LLSlider) {
            root.innerHTML = '<p class="text-xs text-cl-danger py-2">记忆组件脚本未加载（widgets.js）</p>';
            return;
        }
        var q = function (n) { return root.querySelector('[data-mw="' + n + '"]'); };
        Promise.all([
            getJSON('/api/kb/' + kind + '/' + rid + '/fsrs'),
            getJSON('/api/kb/' + kind + '/' + rid + '/curve')
        ]).then(function (rs) {
            if (!document.contains(root)) return; // 片段已切换则丢弃异步回写（guard 同口径）
            // 复审 c3 Minor：重挂前重建骨架换新容器节点，杜绝 LLStars 容器级 keydown 监听累积
            root.innerHTML = memoryPanelHtml();
            var info = rs[0] || {};
            var pts = (rs[1] && rs[1].points) || [];
            global.LLStars.mount(q('diff'), { value: info.difficulty, onChange: function (v) {
                postJSON('/api/kb/' + kind + '/' + rid + '/stars', { difficulty: v })
                    .catch(function (err) { q('diff').textContent = '保存失败：' + err.message; });
            } });
            global.LLStars.mount(q('imp'), { value: info.importance, onChange: function (v) {
                postJSON('/api/kb/' + kind + '/' + rid + '/stars', { importance: v })
                    .catch(function (err) { q('imp').textContent = '保存失败：' + err.message; });
            } });
            global.LLSlider.mount(q('slider'), { value: info.mastery, onCommit: function (v) {
                postJSON('/api/kb/' + kind + '/' + rid + '/mastery_manual', { value: v })
                    .then(function () {
                        // 评审 c3 Minor-4：手动设定后同步详情页头部徽标/进度条（memory 页无槽自然跳过）
                        var ms = scope.querySelector('[data-role="mastery-slot"]');
                        var ps = scope.querySelector('[data-role="progress-slot"]');
                        if (ms) ms.innerHTML = masteryBadge(v);
                        if (ps) ps.innerHTML = progressBar(v);
                        if (document.contains(q('meta'))) q('meta').textContent = '已手动设定熟练度 ' + v + '%（下次真实复习前生效） · 当前为手动设定';
                    })
                    .catch(function (err) { q('slider').textContent = '保存失败：' + err.message; });
            } });
            global.LLCurve.draw(q('curve'), { points: pts, width: 560, height: 140 });
            var meta = '状态：' + (FSR_STATE_NAMES[Number(info.state)] || '未知') +
                (info.due ? ' · 下次复习到期 ' + String(info.due).slice(0, 10) : ' · 尚未排期复习');
            if (Number(info.manual)) meta += ' · 当前为手动设定';
            q('meta').textContent = meta;
        }).catch(function (err) {
            // 评审 c3 Minor-3：失败回滚懒加载标记并重建骨架，收起再展开可重试
            if (document.contains(root)) {
                root.innerHTML = memoryPanelHtml();
                var m0 = root.querySelector('[data-mw="meta"]');
                if (m0) m0.innerHTML = '<span class="text-cl-danger">加载失败：' + esc(err.message) + ' · 收起再展开可重试</span>';
            }
            if (typeof onFail === 'function') onFail();
        });
    }
    // 记页卡片下方折叠面板：首次展开才拉数据懒挂载（kind/rid 为当前卡）
    function bindMemoryToggle(main, kind, rid) {
        var btn = main.querySelector('[data-mw-toggle]');
        var panel = main.querySelector('[data-mw-root]');
        if (!btn || !panel) return;
        btn.addEventListener('click', function () {
            var show = !panel.classList.toggle('hidden');
            btn.textContent = show ? '收起记忆数据' : '记忆数据';
            if (show && panel.dataset.mwMounted !== '1') {
                panel.dataset.mwMounted = '1';
                mountMemoryWidgets(panel, kind, rid, function () { panel.dataset.mwMounted = ''; }); // Minor-3：失败允许重试
            }
        });
    }

    // ---------------- 科目 chip 行（四页共用） ----------------
    // onChange(subject, token)：token 为自增序号，各页渲染前必须校验 token 是否最新，
    // 防止快速切换学科时旧请求后返回覆盖新结果（CodeReview 批4 Major-1）。
    function mountSubjects(root, onChange, preferredSubject) {
        var box = root.querySelector('[data-role="subjects"]');
        if (!box) return;
        var seq = 0;
        box.innerHTML = '<span class="text-xs text-cl-text-3">加载学科中…</span>';
        getJSON('/api/subjects').then(function (list) {
            var subs = list || [];
            if (!subs.length) {
                box.innerHTML = '';
                var main = root.querySelector('[data-role="main"]');
                if (main) main.innerHTML = emptyBox('还没有任何学科', '先到知识库创建一个学科，再回来练习和记忆', '去知识库建学科', 'knowledge_base');
                bindGoLinks(root);
                return;
            }
            // 直达旗标指定学科时以其为初始选中（不在列表则回退第一学科）
            var current = (preferredSubject && subs.indexOf(preferredSubject) >= 0) ? preferredSubject : subs[0];
            box.innerHTML = subs.map(function (s, i) {
                return '<button class="cl-badge transition-colors cursor-pointer" data-subj="' + esc(s) + '">' + esc(s) + '</button>';
            }).join('');
            function paint() {
                box.querySelectorAll('[data-subj]').forEach(function (b) {
                    var on = b.getAttribute('data-subj') === current;
                    b.className = 'cl-badge transition-colors cursor-pointer ' + (on ? 'bg-cl-primary text-white' : 'bg-cl-surface text-cl-text-2 border border-cl-border hover:bg-cl-primary-soft');
                });
            }
            box.addEventListener('click', function (e) {
                var b = e.target.closest('[data-subj]');
                if (!b) return;
                current = b.getAttribute('data-subj');
                paint();
                onChange(current, root.__pmSeq = ++seq);
            });
            paint();
            onChange(current, root.__pmSeq = ++seq);
        }).catch(function (err) {
            box.innerHTML = '<span class="text-xs text-cl-danger">学科加载失败：' + esc(err.message) + '</span>';
        });
    }

    // 学科请求最新 token（挂在 root 上，各页共用）；旧响应到达若 token 非最新则丢弃
    function latestTk(root) { return root.__pmSeq || 0; }

    // ---------------- 错题行（practice_errors 与 memory_errors 共用渲染，交互按页配置） ----------------
    // 手动录入错题（source='manual'）题干为 MD：字符串拼接处先落 data-mdq 占位，DOM 插入后统一 hydrate。
    // 轻量版与知识点页 renderMdInto 同口径（marked 缺失 textContent 回退；截图/附件前缀图走 pybridge 水合）。
    function mdqHtml(src, cls, inline) {
        // inline=true：span 容器（答/选项文字等行内展示位），hydrate 时会剥单段外层 <p>；块位仍用 div
        var tag = inline ? 'span' : 'div';
        return '<' + tag + ' class="' + (cls || 'text-sm font-medium text-cl-text break-words') + '" data-mdq="1" data-src="' + esc(src == null ? '' : String(src)) + '"></' + tag + '>';
    }
    function hydrateMdSlots(scope) {
        if (!scope || !scope.querySelectorAll) return;
        scope.querySelectorAll('[data-mdq]').forEach(function (el) {
            if (el.getAttribute('data-done')) return;
            el.setAttribute('data-done', '1');
            var src = el.getAttribute('data-src') || '';
            // 公式预抽取（md_render.js 公共件）：marked 前把 $…$/$$…$$ 摘成占位符防被 marked 咬坏，
            // sanitize 后再用 KaTeX 回填渲染（渲染发生在清洗之后，不扩大 DOMPurify 白名单）。
            var mm = (window.MdRender && window.MdRender.extract) ? window.MdRender.extract(src) : { text: src, slots: [] };
            // 无 MD 管线（错题练习/错题记忆页未加载 marked/DOMPurify，或 CDN 不可达）：
            // 正文纯文本诚实展示，但公式仍走占位保护+KaTeX 回填（CodeReview Critical-1：公式是本特性主需求）
            if (typeof marked === 'undefined' || !marked.parse
                || typeof window.DOMPurify === 'undefined' || !window.DOMPurify.sanitize) {
                el.textContent = mm.text; // 只含占位符的纯文本，无 marked 输出参与，不经 innerHTML 无注入面
                el.classList.add('whitespace-pre-wrap');
                if (window.MdRender && window.MdRender.applyMath) { try { window.MdRender.applyMath(el, mm.slots); } catch (e) { /* 公式件异常不阻断图文 */ } }
                return;
            }
            var html = marked.parse(mm.text);
            el.innerHTML = (function () {
                // 先 trim：marked 默认输出带尾随换行，不 trim 则单段剥壳正则不命中，span 内残留块级 <p>（CodeReview Major-2）
                var safe = String(window.DOMPurify.sanitize(html)).trim();
                // 行内容器：单段落剥外层 <p> 壳，span 内不留块级元素
                if (el.tagName === 'SPAN') {
                    var mp = /^<p>([\s\S]+)<\/p>$/.exec(safe);
                    if (mp && mp[1].indexOf('</p>') < 0) safe = mp[1];
                }
                return safe;
            })();
            if (window.MdRender && window.MdRender.applyMath) { try { window.MdRender.applyMath(el, mm.slots); } catch (e) { /* 公式件异常不阻断图文 */ } }
            el.querySelectorAll('img').forEach(function (img) {
                var s = img.getAttribute('src') || '';
                try { s = decodeURIComponent(s); } catch (e) { /* 非法编码保留原串 */ }
                if (!/^(截图|attachments)\//i.test(s)) return; // 错题图片统一 vault 根相对前缀（resolveNbImgSrc 口径）
                if (!window.pybridge || !window.pybridge.getImageAsBase64) return;
                img.setAttribute('src', 'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>'); // 占位防相对路径直拉 404
                window.pybridge.getImageAsBase64(s, function (result) {
                    try {
                        var r = JSON.parse(result);
                        if (r.success && r.dataUrl && el.contains(img)) img.setAttribute('src', r.dataUrl);
                    } catch (e) { /* 解析失败保持原路径 */ }
                });
            });
        });
    }
    function errorRow(e, opts) {
        var unrated = isUnrated(e.current_proficiency);
        var prof = unrated ? 0 : Math.max(0, Math.min(100, Number(e.current_proficiency) || 0));
        var reviewed = Number(e.review_status) === 1;
        var manual = e.source === 'manual'; // 手动录入：MD 渲染题干 + 无答题流水
        var h = '<div class="cl-card p-5" data-eid="' + e.id + '">';
        h += '<div class="flex items-start justify-between gap-3">';
        h += '<button class="text-left flex-1 min-w-0 pm-q-toggle" data-toggle="' + e.id + '">'
            + mdqHtml(e.question_content, 'text-sm font-medium text-cl-text break-words max-h-40 overflow-y-auto') + '</button>';
        if (manual) h += '<span class="cl-badge shrink-0 bg-cl-bg text-cl-text-3">手动录入</span>';
        h += '<span class="cl-badge shrink-0 ' + (reviewed ? 'bg-cl-secondary-soft text-cl-secondary' : 'bg-cl-primary-soft text-cl-primary') + '">' + (reviewed ? '已复习' : '待强化') + '</span>';
        h += '</div>';
        h += '<div class="flex items-center gap-3 mt-3">' + progressBar(e.current_proficiency)
            + '<span class="text-xs text-cl-text-3 whitespace-nowrap">' + (unrated ? '未评估' : prof + '%') + '</span></div>';
        // 错题学习单元升级 P2（2026-10-14）：行内属性区=难度/重要度双星（行上可调，0-10 存储分 → /api/kb/error/<id>/stars）
        if (opts && opts.unit) {
            h += '<div class="flex items-center gap-5 mt-2 text-xs text-cl-text-3">'
                + '<span class="flex items-center gap-1.5">难度<span data-us="diff" data-uv="' + (Number(e.difficulty_score) || 5) + '"></span></span>'
                + '<span class="flex items-center gap-1.5">重要度<span data-us="imp" data-uv="' + (Number(e.importance_score) || 5) + '"></span></span></div>';
        }
        h += '<p class="text-xs text-cl-text-3 mt-2">' + icon('clock', 'w-3.5 h-3.5 inline -mt-0.5') + ' 练习于 ' + esc(relTime(e.practice_time)) + '</p>';
        h += '<div class="hidden mt-3 pt-3 border-t border-cl-border space-y-2 text-xs" data-detail="' + e.id + '">';
        // 错题带选项时展开区直接列出（高亮正确项）；存量旧题未落库选项则不显示此块
        h += optionsHtml(e, true);
        // 错题学习单元升级 P1（2026-10-13 用户验收反馈）：答案/解析不再截断、与题干同管线渲染（MD+KaTeX），
        // 展开即完整信息；行内容器用 span 版 mdqHtml，hydrateMdSlots 统一回填
        if (!manual) h += '<div><span class="font-semibold text-cl-text-2">我的答案：</span>'
            + mdqHtml(e.user_answer || '—', (reviewed ? 'text-cl-text' : 'text-cl-danger') + ' inline', true) + '</div>';
        h += '<div><span class="font-semibold text-cl-text-2">正确答案：</span>'
            + mdqHtml(e.correct_answer || '—', 'text-cl-secondary inline', true) + '</div>';
        if (e.explanation) h += '<div><span class="font-semibold text-cl-text-2">解析：</span>'
            + mdqHtml(e.explanation, 'text-cl-text-2 mt-1', false) + '</div>';
        // P2：展开区挂公共记忆面板（曲线+星值+手动熟练度，懒加载）+ 练习历史（首次展开异步拉）
        if (opts && opts.unit) {
            h += '<div><button class="cl-btn-ghost !h-8 !text-xs" data-mw-toggle>记忆数据</button></div>'
                + '<div class="hidden rounded-clbtn bg-cl-surface px-3 py-2" data-mw-root>' + memoryPanelHtml() + '</div>';
            h += '<div><p class="font-semibold text-cl-text-2">练习历史</p>'
                + '<div data-ehistory="' + e.id + '"><p class="text-cl-text-3">加载中…</p></div></div>';
        }
        h += '</div>';
        // P3 行级按钮：练这题（single 组卷）/ 举一反三（analogy 针对该行）
        if (opts && opts.unit && (opts.onSingle || opts.onAnalogy)) {
            h += '<div class="mt-3 flex items-center gap-2">'
                + (opts.onSingle ? '<button class="cl-btn-ghost !h-8 !text-xs" data-pp-single="' + e.id + '">' + icon('dumbbell', 'w-4 h-4') + ' 练这题</button>' : '')
                + (opts.onAnalogy ? '<button class="cl-btn-ghost !h-8 !text-xs" data-pp-analogy="' + e.id + '">' + icon('lightbulb', 'w-4 h-4') + ' 举一反三</button>' : '')
                + '</div>';
        }
        // 标记按钮放在折叠区外常显（批4 自测发现：藏在 hidden 详情内用户无法直接点击）
        if (opts && opts.reviewBtn && !reviewed) {
            h += '<div class="mt-3"><button class="cl-btn-ghost !h-8 !text-xs pm-review-btn" data-eid="' + e.id + '">' + icon('check-circle-2', 'w-4 h-4') + ' 标记已复习</button></div>';
        }
        h += '</div>';
        return h;
    }
    // P2：错题练习历史（重练+举一反三派生流水，后端 practice-history 端点）；前端分页 10/页
    function loadErrorHistory(root, eid) {
        var box = root.querySelector('[data-ehistory="' + eid + '"]');
        if (!box || box.dataset.ehLoaded) return;
        box.dataset.ehLoaded = '1';
        getJSON('/api/kb/errors/' + eid + '/practice-history').then(function (rows) {
            rows = rows || [];
            if (!rows.length) { box.innerHTML = '<p class="text-cl-text-3">还没有练习历史</p>'; return; }
            var page = 1, PER = 10;
            function paint() {
                var pages = Math.max(1, Math.ceil(rows.length / PER));
                if (page > pages) page = pages;
                var h = rows.slice((page - 1) * PER, page * PER).map(function (r) {
                    return '<div class="rounded-clbtn bg-cl-bg px-3 py-2 mb-1">'
                        + mdqHtml(r.question_content, 'text-cl-text-2 max-h-32 overflow-y-auto')
                        + '<p class="text-cl-text-3 mt-1">' + esc(relTime(r.practice_time)) + ' · '
                        + (r.is_correct ? '<span class="text-cl-secondary">答对</span>' : '<span class="text-cl-danger">答错</span>')
                        + ' · 我的答案：' + esc(truncate(r.user_answer, 60)) + '</p></div>';
                }).join('');
                if (pages > 1) h += '<div class="flex items-center gap-2 mt-1">'
                    + '<button class="cl-btn-ghost !h-7 !text-xs" data-eh-prev' + (page <= 1 ? ' disabled' : '') + '>上一页</button>'
                    + '<span class="text-xs text-cl-text-3">' + page + ' / ' + pages + '</span>'
                    + '<button class="cl-btn-ghost !h-7 !text-xs" data-eh-next' + (page >= pages ? ' disabled' : '') + '>下一页</button></div>';
                box.innerHTML = h;
                hydrateMdSlots(box);
                var pv = box.querySelector('[data-eh-prev]'), nx = box.querySelector('[data-eh-next]');
                if (pv) pv.addEventListener('click', function () { page--; paint(); });
                if (nx) nx.addEventListener('click', function () { page++; paint(); });
            }
            paint();
        }).catch(function (err) {
            box.innerHTML = '<p class="text-cl-danger">' + esc(err.message) + '</p>';
        });
    }
    function bindErrorRows(root, opts) {
        hydrateMdSlots(root); // manual 行 MD 题干占位统一渲染（重复调用以 data-done 幂等短路）
        root.querySelectorAll('.pm-q-toggle').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var d = root.querySelector('[data-detail="' + btn.getAttribute('data-toggle') + '"]');
                if (d) d.classList.toggle('hidden');
                // P2：首次展开异步拉该错题的练习历史
                if (opts && opts.unit && d && !d.classList.contains('hidden')) {
                    loadErrorHistory(root, btn.getAttribute('data-toggle'));
                }
            });
        });
        if (opts && opts.unit) {
            // P2：行内属性双星（与记忆面板同一 /api/kb/error/<id>/stars 入口）+ 折叠记忆面板懒挂载
            root.querySelectorAll('.cl-card[data-eid]').forEach(function (card) {
                var eid = card.getAttribute('data-eid');
                [['diff', 'difficulty'], ['imp', 'importance']].forEach(function (pair) {
                    var el = card.querySelector('[data-us="' + pair[0] + '"]');
                    if (!el || !global.LLStars) return;
                    global.LLStars.mount(el, { value: Number(el.getAttribute('data-uv')) || 5, onChange: function (v) {
                        var body = {}; body[pair[1]] = v;
                        postJSON('/api/kb/error/' + eid + '/stars', body)
                            .catch(function (err) { el.textContent = '保存失败：' + err.message; });
                    } });
                });
                bindMemoryToggle(card, 'error', eid);
                if (opts.onSingle) {
                    var bs = card.querySelector('[data-pp-single]');
                    if (bs) bs.addEventListener('click', function () { opts.onSingle(Number(bs.getAttribute('data-pp-single'))); });
                }
                if (opts.onAnalogy) {
                    var ba = card.querySelector('[data-pp-analogy]');
                    if (ba) ba.addEventListener('click', function () { opts.onAnalogy(Number(ba.getAttribute('data-pp-analogy'))); });
                }
            });
        }
        if (opts && opts.reviewBtn) {
            root.querySelectorAll('.pm-review-btn').forEach(function (btn) {
                btn.addEventListener('click', function () {
                    var eid = btn.getAttribute('data-eid');
                    btn.disabled = true;
                    btn.innerHTML = '提交中…';
                    postJSON('/api/kb/errors/' + eid + '/reviewed').then(function () {
                        if (opts.afterReview) opts.afterReview(eid);
                    }).catch(function (err) {
                        btn.disabled = false;
                        btn.textContent = err.message; // textContent 防注入（CodeReview 批4 Major-2）
                    });
                });
            });
        }
    }

    function loadErrors(root, subject, renderFn, token) {
        var main = root.querySelector('[data-role="main"]');
        main.innerHTML = '<p class="text-sm text-cl-text-3 py-6">加载中…</p>';
        getJSON('/api/kb/errors?subject=' + encodeURIComponent(subject)).then(function (rows) {
            if (token != null && token !== latestTk(root)) return; // 旧响应丢弃
            renderFn(rows || [], main);
        }).catch(function (err) {
            if (token != null && token !== latestTk(root)) return;
            main.innerHTML = '<p class="text-sm text-cl-danger py-6">错题加载失败：' + esc(err.message) + '</p>';
        });
    }

    // ---------------- 页1：基于知识点练习 ----------------
    function bootPracticeKnowledge(root) {
        mountSubjects(root, function (subject, token) {
            var main = root.querySelector('[data-role="main"]');
            main.innerHTML = '<p class="text-sm text-cl-text-3 py-6">加载中…</p>';
            getJSON('/api/knowledge/points?subject=' + encodeURIComponent(subject)).then(function (pts) {
                if (token !== latestTk(root)) return; // 旧响应丢弃
                var rows = (pts || []).slice().sort(function (a, b) { return (a.mastery_score || 0) - (b.mastery_score || 0); });
                if (!rows.length) {
                    main.innerHTML = emptyBox('该学科还没有知识点', '先到网课笔记学习并提取知识点，再回来针对性练习', '去录网课笔记', 'online_course_notes');
                    bindGoLinks(root);
                    return;
                }
                var countEl = root.querySelector('[data-role="count"]');
                if (countEl) countEl.textContent = rows.length + ' 个知识点';
                main.innerHTML = '<div class="grid grid-cols-1 md:grid-cols-2 gap-4">' + rows.map(function (p) {
                    var h = '<div class="cl-card p-5" data-kp="' + p.id + '">';
                    h += '<div class="flex items-start justify-between gap-2 mb-2"><h3 class="text-[15px] font-semibold text-cl-text">' + esc(p.point_name) + '</h3>' + masteryBadge(p.mastery_score) + '</div>';
                    if (p.core_description) h += '<p class="text-xs text-cl-text-2 mb-3">' + esc(truncate(p.core_description, 80)) + '</p>';
                    h += progressBar(p.mastery_score);
                    h += '<div class="flex items-center gap-2 mt-4">'
                        + '<button class="cl-btn-ghost !h-8 !text-xs pm-kp-errors" data-kp="' + p.id + '">' + icon('alert-circle', 'w-4 h-4') + ' 相关错题</button>'
                        + '<button class="cl-btn-primary !h-8 !text-xs" data-gopoint="' + esc(String(p.id)) + '" data-goname="' + esc(p.point_name) + '">' + icon('dumbbell', 'w-4 h-4') + ' 去练习</button>'
                        + '</div>';
                    h += '<div class="hidden mt-3 pt-3 border-t border-cl-border space-y-2 text-xs" data-kp-detail="' + p.id + '"></div>';
                    h += '</div>';
                    return h;
                }).join('') + '</div>';
                bindGoLinks(root);
                main.querySelectorAll('.pm-kp-errors').forEach(function (btn) {
                    btn.addEventListener('click', function () {
                        var kp = btn.getAttribute('data-kp');
                        var box = main.querySelector('[data-kp-detail="' + kp + '"]');
                        if (!box) return;
                        if (!box.classList.contains('hidden')) { box.classList.add('hidden'); return; }
                        box.classList.remove('hidden');
                        if (box.dataset.loaded) return;
                        box.innerHTML = '<p class="text-cl-text-3">加载中…</p>';
                        getJSON('/api/kb/errors?subject=' + encodeURIComponent(subject) + '&kp_id=' + kp).then(function (errs) {
                            box.dataset.loaded = '1';
                            if (!errs || !errs.length) { box.innerHTML = '<p class="text-cl-text-3">该知识点暂无错题，保持住</p>'; return; }
                            box.innerHTML = errs.map(function (e) {
                                var q = mdqHtml(e.question_content, 'text-cl-text-2 max-h-40 overflow-y-auto');
                                return '<div class="rounded-clbtn bg-cl-bg px-3 py-2">' + q
                                    + '<p class="text-cl-text-3 mt-1">练习于 ' + esc(relTime(e.practice_time)) + ' · 熟练度 ' + (isUnrated(e.current_proficiency) ? '未评估' : (Number(e.current_proficiency) || 0) + '%') + '</p></div>';
                            }).join('');
                            hydrateMdSlots(box);
                        }).catch(function (err) { box.innerHTML = '<p class="text-cl-danger">' + esc(err.message) + '</p>'; });
                    });
                });
            }).catch(function (err) {
                if (token !== latestTk(root)) return;
                main.innerHTML = '<p class="text-sm text-cl-danger py-6">知识点加载失败：' + esc(err.message) + '</p>';
            });
        });
    }

    // ---------------- 公共练习引擎 pmPractice（错题学习单元升级 P3，2026-10-14） ----------------
    // 组卷→逐题作答→提交→结果面板状态机（自知识点详情页内嵌 prac 状态机收敛为顶层公共件；
    // 错题练习页用本引擎 + error-pool/error-set-submit/analogy 端点）。弹窗形态，ESC/关闭可退。
    // opts: {title, load: () -> Promise(payload{questions}), submit: (qs, ans) -> Promise(payload), onDone(payload)}
    function pmPractice(host, opts) {
        var old = host.querySelector('[data-pp-overlay]');
        if (old) { if (old._onEsc) document.removeEventListener('keydown', old._onEsc); old.remove(); }
        var st = { qs: [], ans: [], idx: 0, gen: 0, busy: false };
        var ov = document.createElement('div');
        ov.setAttribute('data-pp-overlay', '1');
        ov.className = 'fixed inset-0 z-50 flex items-start justify-center bg-black/40 p-4 overflow-y-auto';
        ov.innerHTML = '<div class="cl-card p-6 w-full max-w-2xl my-8" data-pp-card></div>';
        ov._onEsc = function (e) { if (e.key === 'Escape' && !st.busy) close(); };
        document.addEventListener('keydown', ov._onEsc);
        ov.addEventListener('click', function (e) { if (e.target === ov && !st.busy) close(); });
        host.appendChild(ov);
        var card = ov.querySelector('[data-pp-card]');
        function close() { st.gen++; if (ov._onEsc) document.removeEventListener('keydown', ov._onEsc); ov.remove(); }
        function head(sub) {
            return '<div class="flex items-center justify-between mb-3"><div class="cl-section-title">'
                + icon('dumbbell', 'w-4 h-4 text-cl-primary') + ' ' + esc(opts.title) + (sub ? ' · ' + esc(sub) : '') + '</div>'
                + '<button class="text-cl-text-3 hover:text-cl-text" data-pp-close aria-label="关闭">' + icon('x', 'w-4 h-4') + '</button></div>';
        }
        function bindClose() { var b = card.querySelector('[data-pp-close]'); if (b) b.addEventListener('click', close); }
        function fail(text, danger) {
            card.innerHTML = head() + '<p class="text-sm ' + (danger ? 'text-cl-danger' : 'text-cl-text-2') + ' py-2">' + esc(text) + '</p>';
            bindClose();
        }
        card.innerHTML = head('组卷') + '<p class="text-sm text-cl-text-2 py-4">题目加载中，可能需要几十秒，请稍候…</p>';
        bindClose();
        var myGen = ++st.gen;
        Promise.resolve(opts.load()).then(function (r) {
            if (st.gen !== myGen) return;
            if (!r || r.success !== true || !r.questions || !r.questions.length) {
                fail((r && r.error) || '练习启动失败，请稍后重试', !(r && (r.no_errors || r.no_notes)));
                return;
            }
            st.qs = r.questions; st.ans = new Array(r.questions.length).fill(null); st.idx = 0;
            renderQ();
        }).catch(function (e) {
            if (st.gen !== myGen) return;
            fail('题目加载失败：' + (e.message || '未知错误'), true);
        });
        function pickAns() {
            var r = card.querySelector('input[name="pp-ans"]:checked');
            if (r) { st.ans[st.idx] = r.value; return; }
            var inp = card.querySelector('[data-pp-text]');
            if (inp) { var v = inp.value.trim(); st.ans[st.idx] = v ? v : null; }
        }
        function renderQ() {
            var q = st.qs[st.idx], total = st.qs.length;
            var pct = Math.round(((st.idx + 1) / total) * 100);
            var h = head('第 ' + (st.idx + 1) + '/' + total + ' 题');
            h += '<div class="flex items-center gap-3 mb-4"><div class="flex-1 cl-progress"><div class="cl-progress-bar" style="width:' + pct + '%"></div></div>'
                + '<span class="text-xs text-cl-text-3 shrink-0">' + (st.idx + 1) + '/' + total + '</span></div>';
            h += '<div class="flex items-center gap-2 mb-2">'
                + '<span class="cl-badge bg-cl-primary-soft text-cl-primary">题目 ' + (st.idx + 1) + '</span>'
                + '<span class="cl-badge bg-cl-secondary-soft text-cl-secondary">' + esc({ single: '选择题', judge: '判断题', fill: '填空题', short: '简答题' }[q.type] || '选择题') + '</span>'
                + '<span class="text-xs text-cl-text-3">难度: ' + esc(q.difficulty || '中等') + '</span></div>';
            h += mdqHtml(q.question, 'text-sm font-medium text-cl-text mb-3 break-words');
            if (q.type === 'single' || q.type === 'judge') {
                h += '<div class="space-y-2">';
                if (q.type === 'judge') {
                    ['正确', '错误'].forEach(function (v) {
                        h += '<label class="flex items-center gap-3 rounded-clbtn border border-cl-border px-3 py-2 cursor-pointer hover:bg-cl-bg">'
                            + '<input type="radio" name="pp-ans" value="' + esc(v) + '"' + (st.ans[st.idx] === v ? ' checked' : '') + '>'
                            + '<span class="text-[13px] text-cl-text-2">' + esc(v) + '</span></label>';
                    });
                } else {
                    (q.options || []).forEach(function (opt, i) {
                        var letter = String.fromCharCode(65 + i);
                        h += '<label class="flex items-center gap-3 rounded-clbtn border border-cl-border px-3 py-2 cursor-pointer hover:bg-cl-bg">'
                            + '<input type="radio" name="pp-ans" value="' + letter + '"' + (st.ans[st.idx] === letter ? ' checked' : '') + '>'
                            + '<span class="text-[13px] text-cl-text-2"><strong>' + letter + '.</strong> ' + mdqHtml(opt, '', true) + '</span></label>';
                    });
                }
                h += '</div>';
            } else if (q.type === 'fill') {
                h += '<input type="text" data-pp-text maxlength="200" placeholder="填写空格处的答案"'
                    + ' class="w-full rounded-clbtn border border-cl-border px-3 py-2 text-sm text-cl-text focus:outline-none focus:border-cl-primary" value="' + esc(st.ans[st.idx] || '') + '">';
            } else {
                h += '<textarea data-pp-text rows="5" maxlength="2000" placeholder="写下你的答案，提交后由 AI 对照参考答案判分"'
                    + ' class="w-full rounded-clbtn border border-cl-border px-3 py-2 text-sm text-cl-text focus:outline-none focus:border-cl-primary">' + esc(st.ans[st.idx] || '') + '</textarea>';
            }
            h += '<p class="text-xs text-cl-danger mt-2 min-h-4" data-pp-msg></p>';
            h += '<div class="flex items-center justify-between mt-3">'
                + '<button class="cl-btn-ghost !h-8 text-xs" data-pp-prev' + (st.idx === 0 ? ' disabled' : '') + '>上一题</button>'
                + '<button class="cl-btn-primary !h-8 text-xs" data-pp-next>' + (st.idx === total - 1 ? '提交作答' : '下一题') + '</button></div>';
            card.innerHTML = h;
            hydrateMdSlots(card);
            bindClose();
            var msg = card.querySelector('[data-pp-msg]');
            var prev = card.querySelector('[data-pp-prev]');
            if (prev && st.idx > 0) prev.addEventListener('click', function () { pickAns(); st.idx--; renderQ(); });
            card.querySelector('[data-pp-next]').addEventListener('click', function () {
                pickAns();
                if (st.ans[st.idx] == null) { msg.textContent = (q.type === 'short' || q.type === 'fill') ? '请填写答案后继续（AI 判分需要答案）' : '请先作答本题'; return; }
                msg.textContent = '';
                if (st.idx < st.qs.length - 1) { st.idx++; renderQ(); } else submitAll();
            });
        }
        function submitAll() {
            st.busy = true;
            var myGen = st.gen;
            card.innerHTML = head('判分') + '<p class="text-sm text-cl-text-2 py-6 text-center">正在判分…（含简答题时需 AI 判分，稍候）</p>';
            Promise.resolve(opts.submit(st.qs, st.ans)).then(function (r) {
                st.busy = false;
                if (st.gen !== myGen) return;
                if (!r || r.success !== true) {
                    fail('提交判分失败：' + (r && r.credits_insufficient ? '积分不足：' + (r.error || '请先充值') : ((r && r.error) || '未知错误')), true);
                    return;
                }
                renderResult(r);
            }).catch(function (e) {
                st.busy = false;
                if (st.gen !== myGen) return;
                fail('提交异常：' + (e.message || '未知错误'), true);
            });
        }
        function renderResult(r) {
            var wrong = (r.detailed_results || []).filter(function (d) { return !d.is_correct; }).length;
            var h = head('判分结果');
            h += '<div class="text-center py-2">';
            if (r.mastery_score != null && Number(r.mastery_score) >= 0) {
                var score = Number(r.mastery_score) || 0;
                var level = score >= 90 ? '精通' : score >= 70 ? '熟练' : score >= 50 ? '一般' : '待提高';
                h += '<div class="inline-flex items-center justify-center w-20 h-20 rounded-full bg-cl-primary-soft mb-3"><span class="text-2xl font-bold text-cl-primary">' + score + '</span></div>'
                    + '<p class="text-base font-semibold text-cl-text">熟练度：' + level + '</p>';
            }
            h += '<p class="text-xs text-cl-text-2 mt-1">答对 ' + esc(String(r.correct_count)) + '/' + esc(String(r.total_count)) + ' 题'
                + (wrong ? '，错题已更新到错题本' : '，全部答对！') + '</p></div>';
            h += '<div class="mt-4 pt-4 border-t border-cl-border space-y-3">';
            (r.detailed_results || []).forEach(function (d) {
                var oq = st.qs[d.question_index] || {};
                h += '<div class="rounded-clbtn bg-cl-bg px-3 py-2">'
                    + '<div class="flex items-start gap-2">' + (d.is_correct ? icon('check', 'w-4 h-4 text-cl-secondary shrink-0') : icon('x', 'w-4 h-4 text-cl-danger shrink-0'))
                    + mdqHtml(d.question, 'text-[13px] text-cl-text flex-1 break-words max-h-32 overflow-y-auto') + '</div>'
                    + optionsHtml(oq, true, d.user_answer)
                    + '<p class="text-xs text-cl-text-3 mt-1">你的答案：' + mdqHtml(d.user_answer || '未答', '', true) + '　正确答案：' + mdqHtml(d.correct_answer, '', true) + '</p>'
                    + (d.comment ? '<div class="mt-1"><span class="text-xs text-cl-text-3">AI 点评：</span>' + mdqHtml(d.comment, 'text-xs text-cl-text-3 break-words') + '</div>' : '')
                    + (d.explanation ? '<div class="mt-1"><span class="text-xs text-cl-text-3">解析：</span>' + mdqHtml(d.explanation, 'text-xs text-cl-text-3 break-words') + '</div>' : '') + '</div>';
            });
            h += '</div>';
            card.innerHTML = h;
            hydrateMdSlots(card);
            bindClose();
            if (opts.onDone) opts.onDone(r);
        }
    }

    // ---------------- 页2：基于错题练习 ----------------
    function bootPracticeErrors(root) {
        var search = root.querySelector('[data-role="search"]');
        var cache = { subject: '', rows: [] };
        var page = 1, PER = 20; // 错题学习单元升级 P2：前端分页 20 题/页（用户裁定）
        function render(main) {
            var rows = cache.rows;
            var kw = search ? search.value.trim() : '';
            var filtered = kw ? rows.filter(function (r) { return String(r.question_content || '').indexOf(kw) > -1; }) : rows;
            var countEl = root.querySelector('[data-role="count"]');
            if (countEl) countEl.textContent = filtered.length ? ('共 ' + filtered.length + ' 道错题') : '';
            if (!filtered.length) {
                main.innerHTML = emptyBox(kw ? '没有匹配的错题' : '该学科还没有错题', kw ? '' : '去练习模块答几道题，错题会自动收集到这里', kw ? '' : '去练习', 'practice_materials');
                bindGoLinks(root);
                return;
            }
            var pages = Math.max(1, Math.ceil(filtered.length / PER));
            if (page > pages) page = pages;
            var slice = filtered.slice((page - 1) * PER, page * PER);
            var h = '<div class="space-y-3">' + slice.map(function (e) { return errorRow(e, { reviewBtn: false, unit: true, onSingle: startSingle, onAnalogy: startAnalogyRow }); }).join('') + '</div>';
            if (pages > 1) h += '<div class="flex items-center justify-center gap-3 mt-4">'
                + '<button class="cl-btn-ghost !h-8 !text-xs" data-pg-prev' + (page <= 1 ? ' disabled' : '') + '>' + icon('chevron-left', 'w-4 h-4') + ' 上一页</button>'
                + '<span class="text-xs text-cl-text-3">第 ' + page + ' / ' + pages + ' 页</span>'
                + '<button class="cl-btn-ghost !h-8 !text-xs" data-pg-next' + (page >= pages ? ' disabled' : '') + '>下一页 ' + icon('chevron-right', 'w-4 h-4') + '</button></div>';
            main.innerHTML = h;
            bindErrorRows(main, { reviewBtn: false, unit: true, onSingle: startSingle, onAnalogy: startAnalogyRow });
            var pv = main.querySelector('[data-pg-prev]'), nx = main.querySelector('[data-pg-next]');
            if (pv) pv.addEventListener('click', function () { if (page > 1) { page--; render(main); main.scrollIntoView({ block: 'start' }); } });
            if (nx) nx.addEventListener('click', function () { if (page < pages) { page++; render(main); main.scrollIntoView({ block: 'start' }); } });
        }
        // ---- P3 练习闭环：公共引擎 pmPractice + error-pool/error-set-submit/analogy（提交后刷新列表） ----
        function refresh() {
            if (!cache.subject) return;
            getJSON('/api/kb/errors?subject=' + encodeURIComponent(cache.subject)).then(function (rows) {
                cache.rows = rows || [];
                var main = root.querySelector('[data-role="main"]');
                if (main) render(main);
            }).catch(function () { /* 刷新失败保留旧列表 */ });
        }
        function practiceSubmit(qs, ans) {
            return postJSON('/api/practice/error-set-submit', {
                subject_name: cache.subject, questions: qs, answers: ans,
            });
        }
        function startSingle(eid) {
            pmPractice(root, {
                title: '练这题',
                load: function () { return postJSON('/api/practice/error-pool', { subject: cache.subject, mode: 'single', error_id: eid }); },
                submit: practiceSubmit, onDone: refresh,
            });
        }
        function startAnalogyRow(eid) {
            pmPractice(root, {
                title: '举一反三 · 针对该题',
                load: function () { return postJSON('/api/practice/analogy', { subject: cache.subject, error_ids: [eid], count: 3 }); },
                submit: practiceSubmit, onDone: refresh,
            });
        }
        // 简易选项弹窗（题量/勾题）；与知识点页 openPracticeChooser 同构但科目级+分页（PM 公共引擎口径）
        function openModal(inner, onMount) {
            var old = root.querySelector('[data-pp-chooser]');
            if (old) { if (old._onEsc) document.removeEventListener('keydown', old._onEsc); old.remove(); }
            var ov = document.createElement('div');
            ov.setAttribute('data-pp-chooser', '1');
            ov.className = 'fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4';
            ov.innerHTML = '<div class="cl-card p-6 w-full max-w-2xl max-h-[80vh] overflow-y-auto">' + inner + '</div>';
            ov._onEsc = function (e) { if (e.key === 'Escape') closeModal(); };
            document.addEventListener('keydown', ov._onEsc);
            ov.addEventListener('click', function (e) { if (e.target === ov) closeModal(); });
            root.appendChild(ov);
            function closeModal() {
                if (ov._onEsc) document.removeEventListener('keydown', ov._onEsc);
                ov.remove();
            }
            var x = ov.querySelector('[data-ppmc-close]');
            if (x) x.addEventListener('click', closeModal);
            if (onMount) onMount(ov, closeModal);
        }
        function countPicker(titleText, hint, counts, onStart) {
            var sel = counts[1];
            openModal('<div class="flex items-center justify-between mb-3"><div class="cl-section-title">'
                + icon('dumbbell', 'w-4 h-4 text-cl-primary') + ' ' + esc(titleText) + '</div>'
                + '<button class="text-cl-text-3 hover:text-cl-text" data-ppmc-close aria-label="关闭">' + icon('x', 'w-4 h-4') + '</button></div>'
                + '<p class="text-xs text-cl-text-2 mb-4">' + esc(hint) + '</p>'
                + '<div class="flex items-center gap-2 mb-5 flex-wrap">练习题量：'
                + counts.map(function (c) { return '<button class="cl-badge cursor-pointer" data-ppmc-cnt="' + c + '">' + c + ' 题</button>'; }).join('')
                + '</div><div class="flex justify-end"><button class="cl-btn-primary !h-9 text-xs" data-ppmc-start>开始</button></div>',
                function (ov, close) {
                    function paint() {
                        ov.querySelectorAll('[data-ppmc-cnt]').forEach(function (b) {
                            var on = Number(b.getAttribute('data-ppmc-cnt')) === sel;
                            b.className = 'cl-badge cursor-pointer ' + (on ? 'bg-cl-primary-soft text-cl-primary' : 'bg-cl-bg text-cl-text-2 hover:text-cl-text');
                        });
                    }
                    ov.querySelectorAll('[data-ppmc-cnt]').forEach(function (b) {
                        b.addEventListener('click', function () { sel = Number(b.getAttribute('data-ppmc-cnt')); paint(); });
                    });
                    paint();
                    ov.querySelector('[data-ppmc-start]').addEventListener('click', function () { close(); onStart(sel); });
                });
        }
        // 勾选练习：MD 题干 + 熟练度/双星标注 + 分页（20/页）+ 缺判分基准不可勾
        function openManualPicker(onStart) {
            var selectable = cache.rows.filter(function (r) { return String(r.correct_answer || '').trim(); });
            if (!selectable.length) { countPicker('勾选练习', '当前学科没有可判分的错题（缺正确答案），不可勾选练习。', [3, 5, 10], function () {}); return; }
            var chosen = {}, mp = 1, MPER = 20;
            selectable.forEach(function (r) { chosen[r.id] = true; }); // 默认全选（与知识点页勾题弹窗同口径）
            var pages = Math.max(1, Math.ceil(selectable.length / MPER));
            openModal('<div class="flex items-center justify-between mb-3"><div class="cl-section-title">'
                + icon('clipboard-check', 'w-4 h-4 text-cl-primary') + ' 勾选错题练习</div>'
                + '<button class="text-cl-text-3 hover:text-cl-text" data-ppmc-close aria-label="关闭">' + icon('x', 'w-4 h-4') + '</button></div>'
                + '<p class="text-xs text-cl-text-2 mb-3">只练所选错题（直接组卷，不消耗积分）；缺正确答案的行不可勾。</p>'
                + '<div class="space-y-2 max-h-96 overflow-y-auto mb-3" data-ppmc-list></div>'
                + '<div class="flex items-center justify-between"><div class="flex items-center gap-2 text-xs text-cl-text-3" data-ppmc-pg></div>'
                + '<button class="cl-btn-primary !h-9 text-xs" data-ppmc-start></button></div>',
                function (ov, close) {
                    var list = ov.querySelector('[data-ppmc-list]'), pg = ov.querySelector('[data-ppmc-pg]');
                    var startBtn = ov.querySelector('[data-ppmc-start]');
                    function syncStart() {
                        var n = Object.keys(chosen).filter(function (k) { return chosen[k]; }).length;
                        startBtn.disabled = n === 0;
                        startBtn.textContent = '练习所选 ' + n + ' 题';
                    }
                    function paint() {
                        if (mp > pages) mp = pages;
                        list.innerHTML = selectable.slice((mp - 1) * MPER, mp * MPER).map(function (r) {
                            var prof = isUnrated(r.current_proficiency) ? '未评估' : (Number(r.current_proficiency) || 0) + '%';
                            return '<label class="flex items-start gap-2 rounded-clbtn border border-cl-border px-3 py-2 cursor-pointer hover:bg-cl-bg">'
                                + '<input type="checkbox" data-ppmc-row="' + r.id + '"' + (chosen[r.id] ? ' checked' : '') + ' class="mt-0.5 shrink-0">'
                                + '<span class="flex-1 min-w-0">' + mdqHtml(r.question_content, 'text-[13px] text-cl-text break-words max-h-24 overflow-y-auto')
                                + '<span class="block text-[11px] text-cl-text-3 mt-0.5">熟练度 ' + esc(prof) + ' · 难度 ' + esc(String(r.difficulty_score == null ? 5 : r.difficulty_score))
                                + ' · 重要度 ' + esc(String(r.importance_score == null ? 5 : r.importance_score)) + '</span></span></label>';
                        }).join('');
                        hydrateMdSlots(list);
                        list.querySelectorAll('[data-ppmc-row]').forEach(function (cb) {
                            cb.addEventListener('change', function () {
                                chosen[Number(cb.getAttribute('data-ppmc-row'))] = cb.checked;
                                syncStart();
                            });
                        });
                        pg.innerHTML = pages > 1
                            ? '<button class="cl-btn-ghost !h-7 !text-xs" data-ppmc-prev' + (mp <= 1 ? ' disabled' : '') + '>上一页</button>'
                                + '<span>' + mp + ' / ' + pages + '</span>'
                                + '<button class="cl-btn-ghost !h-7 !text-xs" data-ppmc-next' + (mp >= pages ? ' disabled' : '') + '>下一页</button>'
                            : '<span>共 ' + selectable.length + ' 题</span>';
                        var pv = pg.querySelector('[data-ppmc-prev]'), nx = pg.querySelector('[data-ppmc-next]');
                        if (pv) pv.addEventListener('click', function () { if (mp > 1) { mp--; paint(); } });
                        if (nx) nx.addEventListener('click', function () { if (mp < pages) { mp++; paint(); } });
                        syncStart();
                    }
                    paint();
                    startBtn.addEventListener('click', function () {
                        var ids = Object.keys(chosen).filter(function (k) { return chosen[k]; }).map(Number).slice(0, 20);
                        close();
                        onStart(ids);
                    });
                });
        }
        // ---- P4 薄弱点分析报告：列表 / 文字+脑图双视图 / 薄弱点「针对练习」闭环（analogy→pmPractice） ----
        function startTargetedPractice(point, evidence) {
            pmPractice(root, {
                title: '针对练习 · ' + point,
                load: function () {
                    var body = { subject: cache.subject, point: point, count: 5 };
                    if (evidence && evidence.length) body.error_ids = evidence.slice(0, 10);
                    return postJSON('/api/practice/analogy', body);
                },
                submit: practiceSubmit, onDone: refresh,
            });
        }
        // 自绘递归 HTML 树卡片（不引入第三方脑图库）：绿=掌握尚可、红=薄弱，节点带证据错题
        function mindmapHtml(nodes, nested) {
            return '<div class="' + (nested ? 'mt-2 ml-3 pl-3 border-l-2 border-cl-border' : '') + ' space-y-2">' + (nodes || []).map(function (nd) {
                var weak = nd.status === 'weak';
                return '<div class="rounded-clbtn border px-3 py-2 ' + (weak ? 'border-cl-danger/40 bg-cl-danger-soft' : 'border-cl-secondary/40 bg-cl-secondary-soft') + '">'
                    + '<div class="flex items-center gap-2 flex-wrap">'
                    + '<span class="text-[13px] font-semibold ' + (weak ? 'text-cl-danger' : 'text-cl-secondary') + '">' + esc(nd.name) + '</span>'
                    + '<span class="cl-badge text-[11px] ' + (weak ? 'bg-cl-danger-soft text-cl-danger' : 'bg-cl-secondary-soft text-cl-secondary') + '">' + (nd.kind === 'kp' ? '知识点' : '总结点') + (weak ? ' · 薄弱' : ' · 尚可') + '</span>'
                    + ((nd.evidence || []).length ? '<span class="text-[11px] text-cl-text-3">证据错题：' + nd.evidence.map(function (x) { return '#' + x; }).join(' ') + '</span>' : '')
                    + '<span class="ml-auto shrink-0">'
                    + (weak ? '<button class="cl-btn-ghost !h-7 text-[11px]" data-mm-prac="' + esc(nd.name) + '" data-mm-ev="' + esc((nd.evidence || []).join(',')) + '">' + icon('dumbbell', 'w-3.5 h-3.5') + ' 针对练习</button>' : '')
                    + '</span></div>'
                    + ((nd.children || []).length ? mindmapHtml(nd.children, true) : '')
                    + '</div>';
            }).join('') + '</div>';
        }
        function openReports() {
            var old = root.querySelector('[data-wr-overlay]');
            if (old) { if (old._onEsc) document.removeEventListener('keydown', old._onEsc); old.remove(); }
            var ov = document.createElement('div');
            ov.setAttribute('data-wr-overlay', '1');
            ov.className = 'fixed inset-0 z-50 flex items-start justify-center bg-black/40 p-4 overflow-y-auto';
            ov.innerHTML = '<div class="cl-card p-6 w-full max-w-3xl my-8" data-wr-card></div>';
            ov._onEsc = function (e) { if (e.key === 'Escape') close(); };
            document.addEventListener('keydown', ov._onEsc);
            ov.addEventListener('click', function (e) { if (e.target === ov) close(); });
            root.appendChild(ov);
            var card = ov.querySelector('[data-wr-card]');
            function close() { if (ov._onEsc) document.removeEventListener('keydown', ov._onEsc); ov.remove(); }
            function head(title, back) {
                return '<div class="flex items-center justify-between mb-3"><div class="cl-section-title">'
                    + icon('clipboard-check', 'w-4 h-4 text-cl-primary') + ' ' + esc(title) + '</div><div class="flex items-center gap-2">'
                    + (back ? '<button class="cl-btn-ghost !h-7 text-xs" data-wr-back>返回列表</button>' : '')
                    + '<button class="text-cl-text-3 hover:text-cl-text" data-wr-close aria-label="关闭">' + icon('x', 'w-4 h-4') + '</button></div></div>';
            }
            function bindCommon() {
                var x = card.querySelector('[data-wr-close]');
                if (x) x.addEventListener('click', close);
                var bk = card.querySelector('[data-wr-back]');
                if (bk) bk.addEventListener('click', loadList);
            }
            function failBox(title, text, back) {
                card.innerHTML = head(title, back) + '<p class="text-sm text-cl-danger py-2">' + esc(text) + '</p>';
                bindCommon();
            }
            function analyze(scope, ids) {
                card.innerHTML = head('薄弱点分析') + '<p class="text-sm text-cl-text-2 py-6 text-center">AI 正在分析错题，可能需要几十秒，请稍候…（消耗积分）</p>';
                bindCommon();
                var body = { subject: cache.subject, scope: scope };
                if (ids) body.error_ids = ids;
                postJSON('/api/practice/weakness-report', body).then(function (d) {
                    if (!document.contains(card)) return;
                    if (!d || d.success !== true) { failBox('薄弱点分析', (d && d.error) || '分析失败，请稍后重试', true); return; }
                    openDetail({ report_md: d.report_md, nodes: d.nodes, created_time: '' });
                }).catch(function (e) {
                    if (document.contains(card)) failBox('薄弱点分析', '分析请求异常：' + (e.message || '未知错误'), true);
                });
            }
            function openDetail(rep) {
                var tab = 'text';
                function paint() {
                    var h = head('报告详情' + (rep.created_time ? ' · ' + rep.created_time : ''), true)
                        + '<div class="flex items-center gap-2 mb-4">'
                        + '<button class="cl-badge cursor-pointer" data-wr-tab="text">文字报告</button>'
                        + '<button class="cl-badge cursor-pointer" data-wr-tab="map">脑图视图</button></div>';
                    if (tab === 'text') h += mdqHtml(rep.report_md || '', 'text-sm text-cl-text break-words leading-relaxed');
                    else h += mindmapHtml(rep.nodes || [], false);
                    card.innerHTML = h;
                    hydrateMdSlots(card);
                    bindCommon();
                    card.querySelectorAll('[data-wr-tab]').forEach(function (b) {
                        var on = b.getAttribute('data-wr-tab') === tab;
                        b.className = 'cl-badge cursor-pointer ' + (on ? 'bg-cl-primary-soft text-cl-primary' : 'bg-cl-bg text-cl-text-2 hover:text-cl-text');
                        b.addEventListener('click', function () { tab = b.getAttribute('data-wr-tab'); paint(); });
                    });
                    card.querySelectorAll('[data-mm-prac]').forEach(function (b) {
                        b.addEventListener('click', function () {
                            var ev = (b.getAttribute('data-mm-ev') || '').split(',').filter(Boolean).map(Number);
                            startTargetedPractice(b.getAttribute('data-mm-prac'), ev);
                        });
                    });
                }
                paint();
            }
            function loadList() {
                card.innerHTML = head('薄弱点分析报告') + '<p class="text-xs text-cl-text-2 py-4">报告列表加载中…</p>';
                bindCommon();
                getJSON('/api/practice/weakness-reports?subject=' + encodeURIComponent(cache.subject)).then(function (d) {
                    if (!document.contains(card)) return;
                    var reports = (d && d.reports) || [];
                    var h = head('薄弱点分析报告')
                        + '<div class="flex items-center gap-2 mb-4 flex-wrap">'
                        + '<button class="cl-btn-primary !h-9 text-xs" data-wr-global>全局分析（本学科全部错题）</button>'
                        + '<button class="cl-btn-ghost !h-9 text-xs" data-wr-selected>勾选错题分析</button></div>';
                    if (!reports.length) h += '<p class="text-xs text-cl-text-3 py-4">还没有分析报告，点上方按钮生成第一份（消耗积分）</p>';
                    else h += '<div class="space-y-2">' + reports.map(function (r) {
                        return '<div class="rounded-clbtn border border-cl-border px-3 py-2 flex items-center gap-3">'
                            + '<div class="flex-1 min-w-0"><p class="text-[13px] text-cl-text font-medium">' + esc(r.created_time || '') + ' · ' + (r.scope === 'selected' ? '勾选' : '全局') + ' ' + r.error_count + ' 题</p>'
                            + '<p class="text-xs text-cl-text-3 mt-0.5 break-words max-h-16 overflow-y-auto">' + esc(r.preview || '') + '</p></div>'
                            + '<button class="cl-btn-ghost !h-7 text-[11px] shrink-0" data-wr-open="' + r.id + '">' + icon('search', 'w-3.5 h-3.5') + ' 查看</button></div>';
                    }).join('') + '</div>';
                    card.innerHTML = h;
                    bindCommon();
                    card.querySelector('[data-wr-global]').addEventListener('click', function () { analyze('global', null); });
                    card.querySelector('[data-wr-selected]').addEventListener('click', function () {
                        openManualPicker(function (ids) { analyze('selected', ids); });
                    });
                    card.querySelectorAll('[data-wr-open]').forEach(function (b) {
                        b.addEventListener('click', function () {
                            getJSON('/api/practice/weakness-report/' + b.getAttribute('data-wr-open')).then(function (d2) {
                                if (!document.contains(card)) return;
                                if (!d2 || d2.success !== true) { failBox('报告详情', (d2 && d2.error) || '加载失败', true); return; }
                                openDetail(d2.report);
                            }).catch(function (e) {
                                if (document.contains(card)) failBox('报告详情', '加载异常：' + (e.message || '未知错误'), true);
                            });
                        });
                    });
                }).catch(function (e) {
                    if (document.contains(card)) failBox('薄弱点分析报告', '列表加载失败：' + (e.message || '未知错误'));
                });
            }
            loadList();
        }
        var tb = root.querySelector('[data-role="toolbar"]');
        if (tb) tb.addEventListener('click', function (e) {
            var b = e.target.closest('[data-tb]');
            if (!b || !cache.subject) return;
            var act = b.getAttribute('data-tb');
            if (act === 'smart') {
                countPicker('智能练错题', '按 FSRS 三因子（记忆保留率→重要度→难度）自动选最该复习的错题，直接组卷答题，不消耗积分。', [3, 5, 10], function (n) {
                    pmPractice(root, {
                        title: '智能练错题',
                        load: function () { return postJSON('/api/practice/error-pool', { subject: cache.subject, mode: 'smart', count: n }); },
                        submit: practiceSubmit, onDone: refresh,
                    });
                });
            } else if (act === 'manual') {
                openManualPicker(function (ids) {
                    pmPractice(root, {
                        title: '错题练习 · 勾选',
                        load: function () { return postJSON('/api/practice/error-pool', { subject: cache.subject, mode: 'manual', error_ids: ids }); },
                        submit: practiceSubmit, onDone: refresh,
                    });
                });
            } else if (act === 'analogy') {
                countPicker('举一反三', 'AI 智能选取应复习的错题，针对其薄弱考点生成相似新题（消耗积分）；新题答错照常入池。', [3, 5, 10], function (n) {
                    pmPractice(root, {
                        title: '举一反三',
                        load: function () {
                            return postJSON('/api/practice/error-pool', { subject: cache.subject, mode: 'smart', count: n }).then(function (pool) {
                                if (!pool || pool.success !== true) return pool;
                                var ids = pool.questions.map(function (q) { return q.error_id; }).filter(Boolean);
                                return postJSON('/api/practice/analogy', { subject: cache.subject, error_ids: ids, count: n });
                            });
                        },
                        submit: practiceSubmit, onDone: refresh,
                    });
                });
            } else if (act === 'report') {
                openReports(); // P4：报告列表/双视图/针对练习闭环
            }
        });
        if (search) search.addEventListener('keydown', function (e) {
            if (e.key !== 'Enter') return;
            page = 1; // 换搜索词回到第一页
            var main = root.querySelector('[data-role="main"]');
            if (cache.subject && main) render(main);
        });
        mountSubjects(root, function (subject, token) {
            var main = root.querySelector('[data-role="main"]');
            main.innerHTML = '<p class="text-sm text-cl-text-3 py-6">加载中…</p>';
            page = 1; // 换学科回到第一页
            getJSON('/api/kb/errors?subject=' + encodeURIComponent(subject)).then(function (rows) {
                if (token !== latestTk(root)) return; // 旧学科响应不得污染 cache/页面
                cache.subject = subject;
                cache.rows = rows || [];
                render(main);
            }).catch(function (err) {
                if (token !== latestTk(root)) return;
                main.innerHTML = '<p class="text-sm text-cl-danger py-6">错题加载失败：' + esc(err.message) + '</p>';
            });
        });
    }

    // ---------------- 页3：基于知识点记忆（c2：记系列全卡片形态；背面四档自评→FSRS 熟练度） ----------------
    function bootMemoryKnowledge(root) {
        getJSON('/api/dashboard/stats').then(function (s) {
            var el1 = root.querySelector('[data-role="mastered"]');
            var el2 = root.querySelector('[data-role="total"]');
            var bar = root.querySelector('[data-role="bar"]');
            var pctEl = root.querySelector('[data-role="pct"]');
            if (el1) el1.textContent = s.knowledge_mastered;
            if (el2) el2.textContent = '/ ' + s.knowledge_total + ' 个知识点';
            var pct = s.knowledge_total ? Math.round(s.knowledge_mastered * 100 / s.knowledge_total) : null;
            if (bar) bar.style.width = (pct || 0) + '%';
            if (pctEl) pctEl.textContent = (pct == null ? '—' : pct + '%') + '（在学 ' + s.subjects + ' 科 · ' + s.errors_pending + ' 道错题待复习）';
        }).catch(function () { /* 概览保持占位，不用假数据 */ });

        var mode = 'cards';   // 卡片翻转为记忆主模式（用户裁定：记都是卡片形态）
        var rowsAll = [];     // 当前学科数据；队列加载时冻结排序，自评后不重排（防队列位移跳卡）
        var qi = 0, flipped = false;

        function profKey(p) { return isUnrated(p.mastery_score) ? -1 : Number(p.mastery_score); }
        function toggleBar() {
            return '<div class="flex items-center justify-between gap-2 mb-4 flex-wrap">'
                + '<div class="flex gap-1 rounded-clbtn bg-cl-surface p-1 border border-cl-border">'
                + '<button class="cl-badge !px-3 !py-1 cursor-pointer transition-colors ' + (mode === 'cards' ? 'bg-cl-primary text-white' : 'text-cl-text-2 hover:bg-cl-primary-soft') + '" data-modesw="cards">' + icon('layers', 'w-3.5 h-3.5 inline -mt-0.5') + ' 卡片复习</button>'
                + '<button class="cl-badge !px-3 !py-1 cursor-pointer transition-colors ' + (mode === 'list' ? 'bg-cl-primary text-white' : 'text-cl-text-2 hover:bg-cl-primary-soft') + '" data-modesw="list">' + icon('list-tree', 'w-3.5 h-3.5 inline -mt-0.5') + ' 列表</button>'
                + '</div><span class="text-xs text-cl-text-3">' + rowsAll.length + ' 个知识点，最弱优先</span></div>';
        }
        function bindModeSw(main) {
            main.querySelectorAll('[data-modesw]').forEach(function (b) {
                b.addEventListener('click', function () {
                    var m = b.getAttribute('data-modesw');
                    if (m === mode) return;
                    mode = m; qi = 0; flipped = false;
                    render(main);
                });
            });
        }
        function kpRow(p) {
            return '<div class="flex items-center gap-4 py-3 border-b border-cl-border last:border-0">'
                + '<div class="flex-1 min-w-0"><p class="text-sm font-medium text-cl-text truncate">' + esc(p.point_name) + '</p>'
                + '<p class="text-xs text-cl-text-3 mt-0.5">' + esc(truncate(p.core_description, 60) || '') + ' · ' + esc(relTime(p.created_time)) + '</p></div>'
                + '<div class="w-28 shrink-0">' + progressBar(p.mastery_score) + '</div>'
                + masteryBadge(p.mastery_score)
                // 批9：行级直达按钮，不再落在脑图首页
                + '<button class="cl-btn-ghost !h-8 !text-xs shrink-0" data-gopoint="' + esc(String(p.id)) + '" data-goname="' + esc(p.point_name) + '">' + icon('dumbbell', 'w-4 h-4') + ' 巩固</button></div>';
        }
        function renderList(main) {
            var weak = rowsAll.filter(function (p) { return (p.mastery_score || 0) < 80; }).sort(function (a, b) { return (a.mastery_score || 0) - (b.mastery_score || 0); });
            var strong = rowsAll.filter(function (p) { return (p.mastery_score || 0) >= 80; });
            var h = toggleBar();
            h += '<div class="cl-card p-5 mb-4">';
            h += '<div class="cl-section-title mb-2">' + icon('target', 'w-4 h-4 text-cl-primary') + ' 待加强（' + weak.length + '）</div>';
            h += weak.length ? weak.map(kpRow).join('') : '<p class="text-xs text-cl-text-3 py-3">没有低于 80% 的知识点，全部掌握良好</p>';
            h += '</div>';
            h += '<details class="cl-card p-5"><summary class="cl-section-title cursor-pointer select-none">' + icon('check-circle-2', 'w-4 h-4 text-cl-secondary') + ' 已掌握（' + strong.length + '）</summary>'
                + '<div class="mt-2">' + (strong.length ? strong.map(kpRow).join('') : '<p class="text-xs text-cl-text-3 py-3">还没有掌握度 ≥ 80% 的知识点</p>') + '</div></details>';
            h += '<div class="flex gap-3 mt-5">'
                + '<button class="cl-btn-primary" data-go="online_course_notes">' + icon('list-tree', 'w-4 h-4') + ' 查看知识脑图</button>'
                + '<button class="cl-btn-ghost" data-go="practice_materials">' + icon('dumbbell', 'w-4 h-4') + ' 用练习巩固</button></div>';
            main.innerHTML = h;
            bindModeSw(main);
            bindGoLinks(root);
        }
        function renderCards(main) {
            ensureFlipCss();
            if (qi >= rowsAll.length) qi = Math.max(0, rowsAll.length - 1);
            if (qi < 0) qi = 0;
            var p = rowsAll[qi];
            var h = toggleBar();
            h += '<div class="flex items-center justify-between gap-3 mb-3 flex-wrap">';
            h += '<span class="text-xs text-cl-text-3">' + (isUnrated(p.mastery_score) ? '熟练度未评估' : '熟练度 ' + profKey(p) + '%') + ' · 创建于 ' + esc(relTime(p.created_time)) + '</span>';
            h += '<span class="text-[13px] font-medium text-cl-text-2">第 ' + (qi + 1) + ' / ' + rowsAll.length + ' 卡</span></div>';
            // 卡片主体：点卡片翻转（正=知识点名，背=核心描述+四档自评）
            h += '<div class="pm-flip-scene"><div class="pm-flip-card' + (flipped ? ' is-flipped' : '') + '" data-role="flip-card">';
            h += '<div class="pm-flip-face cl-card p-6 flex flex-col">';
            h += '<div class="mb-2">' + masteryBadge(p.mastery_score) + '</div>';
            h += '<p class="text-[17px] leading-relaxed text-cl-text font-semibold break-words">' + esc(p.point_name) + '</p>';
            h += '<div class="mt-auto pt-4 flex items-center justify-between gap-2">'
                + '<span class="text-xs text-cl-text-3">' + icon('refresh-cw', 'w-3.5 h-3.5 inline -mt-0.5') + ' 点击卡片看描述并自评</span>'
                + '<button class="cl-btn-ghost !h-8 !text-xs shrink-0" data-gopoint="' + esc(String(p.id)) + '" data-goname="' + esc(p.point_name) + '">' + icon('dumbbell', 'w-4 h-4') + ' 去练习</button></div>';
            h += '</div>';
            h += '<div class="pm-flip-face pm-flip-back cl-card p-6">';
            h += '<div class="cl-section-title mb-3">' + icon('lightbulb', 'w-4 h-4 text-cl-secondary') + ' 核心描述</div>';
            h += '<p class="text-sm leading-relaxed text-cl-text-2 whitespace-pre-wrap break-words">' + (p.core_description ? esc(truncate(p.core_description, 800)) : '<span class="text-cl-text-3">（该知识点还没有摘要，可在知识库补充）</span>') + '</p>';
            h += rateBarHtml('回忆得怎么样？自评后直接进入 FSRS 间隔重复');
            h += '</div></div></div>';
            // 操作区在卡片外，避免与翻转点击互扰
            h += '<div class="flex items-center justify-between gap-3 mt-4 flex-wrap">';
            h += '<button class="cl-btn-ghost !h-9 text-xs" data-nav="prev"' + (qi <= 0 ? ' disabled' : '') + '>' + icon('chevron-left', 'w-4 h-4') + ' 上一卡</button>';
            h += '<button class="cl-btn-ghost !h-9 text-xs" data-nav="next">下一卡 ' + icon('chevron-right', 'w-4 h-4') + '</button></div>';
            // c3：卡片下方可折叠记忆数据（曲线/星值/手动熟练度，懒加载）
            h += '<div class="mt-2 text-center"><button class="cl-btn-ghost !h-8 !text-xs" data-mw-toggle>记忆数据</button></div>';
            h += '<div class="cl-card p-5 mt-2 hidden" data-mw-root>' + memoryPanelHtml() + '</div>';
            main.innerHTML = h;
            bindModeSw(main);
            var card = main.querySelector('[data-role="flip-card"]');
            if (card) card.addEventListener('click', function (ev) {
                if (ev.target.closest('button')) return; // 自评/去练习按钮不触发翻面（integ flipToggle 同口径）
                flipped = !flipped;
                card.classList.toggle('is-flipped', flipped);
            });
            main.querySelectorAll('[data-nav]').forEach(function (b) {
                b.addEventListener('click', function () {
                    var act = b.getAttribute('data-nav');
                    if (act === 'prev') { if (qi > 0) { qi--; flipped = false; renderCards(main); } return; }
                    if (act === 'next') { qi = Math.min(qi + 1, rowsAll.length - 1); flipped = false; renderCards(main); }
                });
            });
            bindRateBar(main, function (key, btn) {
                // 请求在途锁定导航/模式/自评按钮，防叠加点击跳卡（记错题同口径）
                var lockSel = main.querySelectorAll('[data-nav], [data-modesw], [data-rate]');
                lockSel.forEach(function (x) { x.disabled = true; });
                var tkRate = latestTk(root);
                postJSON('/api/kb/kp/' + p.id + '/rate', { self_assessment: key }).then(function (d) {
                    if (tkRate !== latestTk(root)) return; // 已换学科，新 load 自会渲染
                    if (d && Number(d.mastery) >= 0) p.mastery_score = d.mastery; // 队列不重排，仅刷新展示值
                    flipped = false;
                    qi = Math.min(qi + 1, rowsAll.length - 1); // 自动下一张（末卡停留）
                    renderCards(main);
                }).catch(function (err) {
                    lockSel.forEach(function (x) { x.disabled = false; });
                    btn.textContent = err.message; // textContent 防注入
                });
            });
            bindMemoryToggle(main, 'kp', p.id);
            bindGoLinks(root); // 正面「去练习」直达按钮
        }
        function render(main) {
            if (mode === 'list') renderList(main); else renderCards(main);
        }
        mountSubjects(root, function (subject, token) {
            var main = root.querySelector('[data-role="main"]');
            main.innerHTML = '<p class="text-sm text-cl-text-3 py-6">加载中…</p>';
            getJSON('/api/knowledge/points?subject=' + encodeURIComponent(subject)).then(function (pts) {
                if (token !== latestTk(root)) return; // 旧响应丢弃
                rowsAll = (pts || []).slice().sort(function (a, b) { return profKey(a) - profKey(b); }); // 进入本学科：最弱优先冻结队列
                qi = 0; flipped = false;
                if (!rowsAll.length) {
                    main.innerHTML = emptyBox('该学科还没有知识点', '先到网课笔记学习并提取知识点', '去录网课笔记', 'online_course_notes');
                    bindGoLinks(root);
                    return;
                }
                render(main);
            }).catch(function (err) {
                if (token !== latestTk(root)) return;
                main.innerHTML = '<p class="text-sm text-cl-danger py-6">知识点加载失败：' + esc(err.message) + '</p>';
            });
        });
    }

    // ---------------- 页4：基于错题记忆（默认卡片复习：按推荐序无脑连续翻卡；可切列表模式） ----------------
    function bootMemoryErrors(root) {
        var currentSubject = '';
        var cache = { rows: [] };
        var mode = 'cards';   // cards | list（卡片翻转为复习主模式，用户裁定）
        var round = 'pending'; // pending=待复习队列 | done=已复习巩固轮
        var queue = [], qi = 0, flipped = false;
        // 总览推荐直达旗标（10s 内有效，消费即清；首次渲染定位到对应卡后失效）
        var startEid = null;
        var startSubject = null;  // 非第一学科的直达必须同时消费学科，否则首科队列找不到目标卡
        try {
            var rawR = localStorage.getItem('pm_pending_review');
            if (rawR) {
                localStorage.removeItem('pm_pending_review');
                var pr = JSON.parse(rawR);
                if (pr && pr.eid && Date.now() - (pr.ts || 0) <= 10000) {
                    startEid = String(pr.eid);
                    startSubject = pr.subject ? String(pr.subject) : null;
                }
            }
        } catch (e) { /* 旗标损坏不影响主流程 */ }

        function profKey(r) {
            // null/空串视作未评估排最前（Number(null)===0 会错排，与后端推荐 prof is None 排前同口径）
            if (r.current_proficiency === null || r.current_proficiency === undefined || String(r.current_proficiency).trim() === '') return -1;
            var p = Number(r.current_proficiency);
            return (isNaN(p) || p < 0) ? -1 : p; // 未评估视作最弱排前（与总览推荐同口径）
        }
        function sortedByProf(list) {
            return list.slice().sort(function (a, b) { return profKey(a) - profKey(b); });
        }
        function pendingList(rows) { return sortedByProf(rows.filter(function (r) { return Number(r.review_status) !== 1; })); }
        function doneList(rows) { return sortedByProf(rows.filter(function (r) { return Number(r.review_status) === 1; })); }

        function renderStat(rows) {
            var total = rows.length;
            var done = doneList(rows).length;
            var pct = total ? Math.round(done * 100 / total) : 0;
            var statEl = root.querySelector('[data-role="stat"]');
            if (statEl) statEl.innerHTML = '<div class="flex items-center gap-4">'
                + '<span class="text-[22px] font-bold text-cl-primary">' + done + '</span><span class="text-sm text-cl-text-2">/ ' + total + ' 道已复习</span>'
                + '<div class="flex-1 max-w-[240px]">' + '<div class="cl-progress"><div class="cl-progress-bar" style="width:' + pct + '%"></div></div>'
                + '<p class="text-xs text-cl-text-3 mt-1">复习完成 ' + (total ? pct + '%' : '—') + '</p></div></div>';
        }
        function toggleBar(pendCount) {
            return '<div class="flex items-center justify-between gap-2 mb-4 flex-wrap">'
                + '<div class="flex gap-1 rounded-clbtn bg-cl-surface p-1 border border-cl-border">'
                + '<button class="cl-badge !px-3 !py-1 cursor-pointer transition-colors ' + (mode === 'cards' ? 'bg-cl-primary text-white' : 'text-cl-text-2 hover:bg-cl-primary-soft') + '" data-modesw="cards">' + icon('layers', 'w-3.5 h-3.5 inline -mt-0.5') + ' 卡片复习</button>'
                + '<button class="cl-badge !px-3 !py-1 cursor-pointer transition-colors ' + (mode === 'list' ? 'bg-cl-primary text-white' : 'text-cl-text-2 hover:bg-cl-primary-soft') + '" data-modesw="list">' + icon('list-tree', 'w-3.5 h-3.5 inline -mt-0.5') + ' 列表</button>'
                + '</div><span class="text-xs text-cl-text-3">' + (round === 'done' ? '已复习巩固轮' : pendCount + ' 道待复习，按熟练度升序') + '</span></div>';
        }

        function renderList(main, rows) {
            if (!rows.length) {
                main.innerHTML = toggleBar(0) + emptyBox('该学科还没有错题', '错题是学习的宝藏，去练习几道题吧', '去练习', 'practice_materials');
                bindModeSw(main); bindGoLinks(root);
                return;
            }
            var list = pendingList(rows).concat(doneList(rows));
            main.innerHTML = toggleBar(pendingList(rows).length) + '<div class="space-y-3">' + list.map(function (e) { return errorRow(e, { reviewBtn: true }); }).join('') + '</div>';
            bindModeSw(main);
            bindErrorRows(main, { reviewBtn: true, afterReview: function () { load(latestTk(root)); } });
        }
        function bindModeSw(main) {
            main.querySelectorAll('[data-modesw]').forEach(function (b) {
                b.addEventListener('click', function () {
                    var m = b.getAttribute('data-modesw');
                    if (m === mode) return;
                    mode = m; qi = 0; flipped = false;
                    render(cache.rows, main);
                });
            });
        }

        function renderCards(main, rows) {
            ensureFlipCss();
            if (!rows.length) {
                main.innerHTML = toggleBar(0) + emptyBox('该学科还没有错题', '错题会自动收集到这里，做成卡片一道道翻着复习', '去练习', 'practice_materials');
                bindModeSw(main); bindGoLinks(root);
                return;
            }
            var pend = pendingList(rows);
            if (round === 'pending' && !pend.length) {
                // 待复习全部翻完 → 完成页，可进入已复习巩固轮继续无脑翻
                main.innerHTML = toggleBar(0)
                    + '<div class="cl-card p-10 text-center">' + icon('check-circle-2', 'w-10 h-10 text-cl-secondary')
                    + '<p class="text-[15px] font-semibold text-cl-text mt-3">本学科错题全部复习完了</p>'
                    + '<p class="text-xs text-cl-text-3 mt-1">趁热打铁：可以把已复习的卡片再过一轮巩固</p>'
                    + '<div class="flex justify-center gap-3 mt-5">'
                    + (doneList(rows).length ? '<button class="cl-btn-primary !h-9 text-xs" data-round="done">' + icon('refresh-cw', 'w-4 h-4') + ' 再翻已复习的</button>' : '')
                    + '<button class="cl-btn-ghost !h-9 text-xs" data-modesw="list">列表查看</button></div></div>';
                bindModeSw(main);
                var rb = main.querySelector('[data-round="done"]');
                if (rb) rb.addEventListener('click', function () { round = 'done'; qi = 0; flipped = false; render(cache.rows, main); });
                return;
            }
            if (round === 'done' && !doneList(rows).length) { round = 'pending'; }
            queue = round === 'pending' ? pend : doneList(rows);
            // 直达旗标：首次构建队列时定位到推荐题；旧题不在本队列则从头翻
            if (startEid != null) {
                for (var si = 0; si < queue.length; si++) { if (String(queue[si].id) === startEid) { qi = si; break; } }
                startEid = null;
            }
            if (qi >= queue.length) qi = Math.max(0, queue.length - 1);
            if (qi < 0) qi = 0;
            var e = queue[qi];
            if (!e) { main.innerHTML = toggleBar(0); return; }
            var typeName = QUESTION_TYPE_NAMES[e.question_type] || '';
            var unratedP = isUnrated(e.current_proficiency);
            var manualE = e.source === 'manual'; // 手动录入：题面 MD 渲染，背面不展示空答题流水
            var h = toggleBar(pend.length);
            h += '<div class="flex items-center justify-between gap-3 mb-3 flex-wrap">';
            h += '<div class="flex items-center gap-2">' + (typeName ? '<span class="cl-badge bg-cl-primary-soft text-cl-primary">' + esc(typeName) + '</span>' : '')
                + (manualE ? '<span class="cl-badge bg-cl-bg text-cl-text-3">手动录入</span>' : '')
                + '<span class="cl-badge ' + (round === 'done' ? 'bg-cl-secondary-soft text-cl-secondary' : 'bg-cl-bg text-cl-text-2') + '">' + (round === 'done' ? '巩固轮' : '待复习') + '</span>'
                + '<span class="text-xs text-cl-text-3">' + (unratedP ? '熟练度未评估' : '熟练度 ' + profKey(e) + '%') + ' · 练习于 ' + esc(relTime(e.practice_time)) + '</span></div>';
            h += '<span class="text-[13px] font-medium text-cl-text-2">第 ' + (qi + 1) + ' / ' + queue.length + ' 题</span></div>';
            // 卡片主体：点卡片翻转（正=题干+选项，背=答案+解析）
            h += '<div class="pm-flip-scene"><div class="pm-flip-card' + (flipped ? ' is-flipped' : '') + '" data-role="flip-card">';
            h += '<div class="pm-flip-face cl-card p-6 flex flex-col">';
            h += mdqHtml(e.question_content || '（题干缺失）', 'text-[15px] leading-relaxed text-cl-text font-medium break-words max-h-[42vh] overflow-y-auto');
            h += optionsHtml(e, false);
            h += '<p class="mt-auto pt-4 text-center text-xs text-cl-text-3">' + icon('refresh-cw', 'w-3.5 h-3.5 inline -mt-0.5') + ' 点击卡片看答案与解析</p>';
            h += '</div>';
            h += '<div class="pm-flip-face pm-flip-back cl-card p-6">';
            h += '<div class="cl-section-title mb-3">' + icon('lightbulb', 'w-4 h-4 text-cl-secondary') + ' 答案与解析</div>';
            h += '<p class="text-sm leading-relaxed"><span class="font-semibold text-cl-text-2">正确答案：</span>' + mdqHtml(e.correct_answer || '—', 'text-cl-secondary font-medium', true) + '</p>';
            if (!manualE) h += '<p class="text-sm leading-relaxed mt-2"><span class="font-semibold text-cl-text-2">我的答案：</span>' + mdqHtml(e.user_answer || '—', 'text-cl-danger', true) + '</p>';
            h += optionsHtml(e, true);
            if (!e.options || !e.options.length) {
                h += '<p class="text-xs text-cl-text-3 mt-3 rounded-clbtn bg-cl-bg px-3 py-2">该题未保存选项（旧数据），仅对照答案与解析复习</p>';
            }
            if (e.explanation) h += '<div class="mt-3"><span class="text-sm font-semibold text-cl-text-2">解析：</span>' + mdqHtml(e.explanation, 'text-sm leading-relaxed text-cl-text-2 break-words max-h-40 overflow-y-auto') + '</div>';
            // c2：背面四档自评 = FSRS 计分；待复习轮自评即视为完成本次复习（自动标记已复习并下一题）
            h += rateBarHtml(round === 'done'
                ? '回忆得怎么样？巩固轮可再次自评，不改变复习状态'
                : '回忆得怎么样？自评即完成本次复习，自动进入下一题');
            h += '</div></div></div>';
            // 操作区在卡片外，避免与翻转点击互扰
            h += '<div class="flex items-center justify-between gap-3 mt-4 flex-wrap">';
            h += '<button class="cl-btn-ghost !h-9 text-xs" data-nav="prev"' + (qi <= 0 ? ' disabled' : '') + '>' + icon('chevron-left', 'w-4 h-4') + ' 上一题</button>';
            h += '<button class="cl-btn-ghost !h-9 text-xs" data-nav="next">下一题 ' + icon('chevron-right', 'w-4 h-4') + '</button></div>';
            // c3：卡片下方可折叠记忆数据（错题 retrievability 无历史列，曲线仅熟练度红线）
            h += '<div class="mt-2 text-center"><button class="cl-btn-ghost !h-8 !text-xs" data-mw-toggle>记忆数据</button></div>';
            h += '<div class="cl-card p-5 mt-2 hidden" data-mw-root>' + memoryPanelHtml() + '</div>';
            main.innerHTML = h;
            hydrateMdSlots(main); // manual 错题翻卡：题面 MD 占位渲染
            bindModeSw(main);
            var card = main.querySelector('[data-role="flip-card"]');
            if (card) card.addEventListener('click', function (ev) {
                if (ev.target.closest('button')) return; // 背面自评按钮不触发翻回（integ flipToggle 同口径）
                flipped = !flipped;
                card.classList.toggle('is-flipped', flipped);
            });
            main.querySelectorAll('[data-nav]').forEach(function (b) {
                b.addEventListener('click', function () {
                    var act = b.getAttribute('data-nav');
                    if (act === 'prev') { if (qi > 0) { qi--; flipped = false; render(cache.rows, main); } return; }
                    if (act === 'next') { if (qi < queue.length - 1) { qi++; } flipped = false; render(cache.rows, main); return; }
                });
            });
            // c2：背面四档自评→FSRS 计分（待复习轮同时自动标记已复习），取代旧单一「标记已复习」按钮
            bindRateBar(main, function (key, btn) {
                // 请求在途期间锁定导航/模式/自评，防 qi 位移与队列左移叠加跳卡（CodeReview Minor-6 同口径）
                var lockSel = main.querySelectorAll('[data-nav], [data-modesw], [data-rate]');
                lockSel.forEach(function (x) { x.disabled = true; });
                var tkRate = latestTk(root);
                var ratedEid = e.id;
                var rateRound = round; // 异步回包前固定当前轮次，防中途切轮误写状态
                postJSON('/api/kb/error/' + ratedEid + '/rate', { self_assessment: key })
                    .then(function (d) {
                        if (rateRound !== 'pending') return d;
                        return postJSON('/api/kb/errors/' + ratedEid + '/reviewed').then(function () { return d; });
                    })
                    .then(function (d) {
                        if (tkRate !== latestTk(root)) return; // 已换学科，新 load 自会渲染
                        // CodeReview c2 Minor：done 轮不写回 proficiency 展示值，保持 doneList 重排稳定（防跳卡）；
                        // pending 轮必须写回（review_status 移出队列依熟练度序重建）
                        for (var ri = 0; ri < cache.rows.length; ri++) {
                            if (String(cache.rows[ri].id) === String(ratedEid)) {
                                if (rateRound === 'pending') {
                                    if (d && Number(d.mastery) >= 0) cache.rows[ri].current_proficiency = d.mastery;
                                    cache.rows[ri].review_status = 1;
                                }
                            }
                        }
                        flipped = false;
                        if (rateRound === 'done') qi += 1; // pending 轮本题移出队列，render 重建后下一题自然顶上
                        render(cache.rows, main);
                    })
                    .catch(function (err) {
                        lockSel.forEach(function (x) { x.disabled = false; });
                        btn.textContent = err.message; // textContent 防注入
                    });
            });
            bindMemoryToggle(main, 'error', e.id);
        }

        function render(rows, main) {
            cache.rows = rows || [];
            renderStat(cache.rows);
            if (mode === 'list') renderList(main, cache.rows);
            else renderCards(main, cache.rows);
        }
        function load(token) {
            qi = 0; flipped = false; // 换学科重置翻卡位置
            loadErrors(root, currentSubject, render, token);
        }
        mountSubjects(root, function (subject, token) {
            currentSubject = subject;
            round = 'pending';
            load(token);
        }, startSubject); // 直达旗标带学科：非第一学科也能落在正确学科队列上（CodeReview Major-2）
    }

    // ---------------- 页0（u8）：练·科目统计首页 ----------------
    function bootPracticeOverview(root) {
        bindGoLinks(root); // 静态子模式入口卡
        var main = root.querySelector('[data-role="main"]');
        getJSON('/api/practice/overview').then(function (d) {
            // u9 CodeReview M-3：双层契约内层 success 显式校验（P032 约定）
            if (!d || d.success !== true) throw new Error('统计接口返回异常');
            var subs = (d && d.subjects) || [];
            var sum = d.summary || {};
            var countEl = root.querySelector('[data-role="count"]');
            if (countEl) countEl.textContent = subs.length ? (subs.length + ' 个科目 · ' + sum.knowledge_total + ' 个知识点') : '';
            if (!subs.length) {
                main.innerHTML = emptyBox('还没有任何学科', '先到知识库创建学科，去网课笔记学习后这里会出现各科练习概况', '去知识库建学科', 'knowledge_base');
                bindGoLinks(root);
                return;
            }
            function metric(v, label) {
                return '<div class="text-center"><div class="text-[20px] font-bold text-cl-text leading-none">' + (v == null ? '—' : esc(String(v))) + '</div>'
                    + '<div class="text-[11px] text-cl-text-3 mt-1">' + esc(label) + '</div></div>';
            }
            function pointLine(label, p) {
                if (!p) return '<p class="text-xs text-cl-text-3"><span class="font-medium">' + esc(label) + '：</span>暂无（还没有评估记录）</p>';
                return '<p class="text-xs text-cl-text-2 truncate"><span class="font-medium">' + esc(label) + '：</span>'
                    + esc(p.name) + ' · ' + (isUnrated(p.score) ? '未评估' : (Number(p.score) || 0) + '%') + '</p>';
            }
            function subjectCard(s) {
                var h = '<div class="cl-card p-6" data-subject="' + esc(s.subject) + '">';
                h += '<div class="flex items-center justify-between gap-3 mb-4">';
                h += '<h3 class="text-[16px] font-semibold text-cl-text truncate">' + icon('book-open', 'w-4 h-4 text-cl-primary inline -mt-0.5') + ' ' + esc(s.subject) + '</h3>';
                h += '<span class="cl-badge bg-cl-bg text-cl-text-2 shrink-0">' + (s.practice_this_week > 0 ? '本周已练 ' + esc(s.practice_this_week) + ' 题' : (s.last_practice_time ? '本周未练' : '从未练习')) + '</span>';
                h += '</div>';
                h += '<div class="grid grid-cols-4 gap-2 mb-4">'
                    + metric(s.knowledge_count, '知识点')
                    + metric(s.practice_count, '练习题数')
                    + metric(s.errors_pending, '待强化错题')
                    + metric(s.notes_count, '关联笔记') + '</div>';
                h += '<div class="flex items-center gap-3 mb-4">' + progressBar(s.avg_mastery)
                    + '<span class="text-xs text-cl-text-3 whitespace-nowrap">' + (s.avg_mastery == null ? '平均掌握度未评估' : '平均掌握度 ' + s.avg_mastery + '%') + '</span></div>';
                h += '<div class="space-y-1.5 mb-4">' + pointLine('最熟练', s.best_point) + pointLine('最不熟练', s.worst_point) + '</div>';
                if (s.recommend && s.recommend.length) {
                    h += '<div class="cl-section-title mb-2">' + icon('sparkles', 'w-4 h-4 text-cl-primary') + ' 推荐练习</div>';
                    h += '<div class="space-y-2">' + s.recommend.map(function (r) {
                        return '<div class="flex items-center gap-3 rounded-clbtn bg-cl-bg px-3 py-2">'
                            + '<div class="flex-1 min-w-0"><p class="text-[13px] font-medium text-cl-text truncate">' + esc(r.name) + '</p>'
                            + '<p class="text-[11px] text-cl-text-3">' + esc(r.reason) + '</p></div>'
                            + '<button class="cl-btn-primary !h-7 !text-[11px] shrink-0" data-gopoint="' + esc(String(r.id)) + '" data-goname="' + esc(r.name) + '">' + icon('dumbbell', 'w-3.5 h-3.5') + ' 去练习</button></div>';
                    }).join('') + '</div>';
                } else {
                    h += '<p class="text-xs text-cl-text-3">该科目还没有知识点，先到网课笔记学习并提取知识点</p>';
                }
                h += '</div>';
                return h;
            }
            main.innerHTML = '<div class="grid grid-cols-1 md:grid-cols-2 gap-4">' + subs.map(subjectCard).join('') + '</div>';
            bindGoLinks(root); // 含 data-gopoint 直达按钮（u10 已改落点：直达 knowledge_point 详情页）
        }).catch(function (err) {
            main.innerHTML = '<p class="text-sm text-cl-danger py-6">统计加载失败：' + esc(err.message) + '</p>';
        });
    }

    // ---------------- 页0（u9）：记·科目统计首页 ----------------
    function bootMemoryOverview(root) {
        bindGoLinks(root); // 静态子模式入口卡（去重保护见 bindGoLinks）
        var main = root.querySelector('[data-role="main"]');
        getJSON('/api/memory/overview').then(function (d) {
            // u9 CodeReview M-3：双层契约内层 success 显式校验（P032 约定）
            if (!d || d.success !== true) throw new Error('统计接口返回异常');
            var subs = (d && d.subjects) || [];
            var sum = d.summary || {};
            var countEl = root.querySelector('[data-role="count"]');
            if (countEl) countEl.textContent = subs.length ? (sum.to_learn_total + ' 个知识点待记 · ' + sum.errors_pending_total + ' 道错题待复习') : '';
            if (!subs.length) {
                main.innerHTML = emptyBox('还没有任何学科', '先到知识库创建学科，去网课笔记学习后这里会出现各科记忆概况', '去知识库建学科', 'knowledge_base');
                bindGoLinks(root);
                return;
            }
            function metric(v, label) {
                return '<div class="text-center"><div class="text-[20px] font-bold text-cl-text leading-none">' + (v == null ? '—' : esc(String(v))) + '</div>'
                    + '<div class="text-[11px] text-cl-text-3 mt-1">' + esc(label) + '</div></div>';
            }
            function pointLine(label, p) {
                if (!p) return '<p class="text-xs text-cl-text-3"><span class="font-medium">' + esc(label) + '：</span>暂无（还没有评估记录）</p>';
                return '<p class="text-xs text-cl-text-2 truncate"><span class="font-medium">' + esc(label) + '：</span>'
                    + esc(p.name) + ' · ' + (isUnrated(p.score) ? '未评估' : (Number(p.score) || 0) + '%') + '</p>';
            }
            function subjectCard(s) {
                var h = '<div class="cl-card p-6" data-subject="' + esc(s.subject) + '">';
                h += '<div class="flex items-center justify-between gap-3 mb-4">';
                h += '<h3 class="text-[16px] font-semibold text-cl-text truncate">' + icon('book-open', 'w-4 h-4 text-cl-primary inline -mt-0.5') + ' ' + esc(s.subject) + '</h3>';
                h += '<span class="cl-badge bg-cl-bg text-cl-text-2 shrink-0">' + (s.errors_pending > 0 ? (esc(s.errors_pending) + ' 道错题待复习') : (s.last_error_time ? ('最近错题 ' + esc(relTime(s.last_error_time))) : '暂无待复习错题')) + '</span>';
                h += '</div>';
                h += '<div class="grid grid-cols-4 gap-2 mb-4">'
                    + metric(s.to_learn_count, '待记知识点')
                    + metric(s.mastered_count, '已掌握')
                    + metric(s.error_cards, '错题卡片')
                    + metric(s.errors_reviewed, '已复习') + '</div>';
                h += '<div class="flex items-center gap-3 mb-4">' + progressBar(s.avg_mastery)
                    + '<span class="text-xs text-cl-text-3 whitespace-nowrap">' + (s.avg_mastery == null ? '平均掌握度未评估' : '平均掌握度 ' + s.avg_mastery + '%') + '</span></div>';
                h += '<div class="space-y-1.5 mb-4">' + pointLine('记得最牢', s.strongest_point) + pointLine('最薄弱', s.weakest_point) + '</div>';
                if (s.most_frequent_error) {
                    h += '<p class="text-xs text-cl-text-2 mb-4 rounded-clbtn bg-cl-bg px-3 py-2">' + icon('flame', 'w-3.5 h-3.5 text-cl-danger inline -mt-0.5')
                        + ' <span class="font-medium">错得最多：</span>' + esc(truncate(s.most_frequent_error.question, 60)) + '（错了 ' + esc(s.most_frequent_error.count) + ' 次）</p>';
                }
                if (s.recommend_points && s.recommend_points.length) {
                    h += '<div class="cl-section-title mb-2">' + icon('sparkles', 'w-4 h-4 text-cl-primary') + ' 推荐记忆</div>';
                    h += '<div class="space-y-2 mb-4">' + s.recommend_points.map(function (r) {
                        return '<div class="flex items-center gap-3 rounded-clbtn bg-cl-bg px-3 py-2">'
                            + '<div class="flex-1 min-w-0"><p class="text-[13px] font-medium text-cl-text truncate">' + esc(r.name) + '</p>'
                            + '<p class="text-[11px] text-cl-text-3">' + esc(r.reason) + '</p></div>'
                            + '<button class="cl-btn-primary !h-7 !text-[11px] shrink-0" data-gopoint="' + esc(String(r.id)) + '" data-goname="' + esc(r.name) + '">' + icon('brain', 'w-3.5 h-3.5') + ' 去记忆</button></div>';
                    }).join('') + '</div>';
                } else if (s.knowledge_total === 0) {
                    h += '<p class="text-xs text-cl-text-3 mb-4">该科目还没有知识点，先到网课笔记学习并提取知识点</p>';
                }
                if (s.recommend_errors && s.recommend_errors.length) {
                    h += '<div class="cl-section-title mb-2">' + icon('history', 'w-4 h-4 text-cl-primary') + ' 推荐复习错题</div>';
                    h += '<div class="space-y-2">' + s.recommend_errors.map(function (r) {
                        return '<div class="flex items-center gap-3 rounded-clbtn bg-cl-bg px-3 py-2">'
                            + '<div class="flex-1 min-w-0"><p class="text-[13px] font-medium text-cl-text truncate">' + esc(r.question) + '</p>'
                            + '<p class="text-[11px] text-cl-text-3">' + esc(r.reason) + '</p></div>'
                            // 直达翻卡：写入带 eid 旗标，记错题页卡片模式从该题开始无脑翻
                            + '<button class="cl-btn-ghost !h-7 !text-[11px] shrink-0" data-gorev="' + esc(String(r.id)) + '" data-gorevsubj="' + esc(s.subject) + '">' + icon('refresh-cw', 'w-3.5 h-3.5') + ' 去复习</button></div>';
                    }).join('') + '</div>';
                }
                h += '</div>';
                return h;
            }
            main.innerHTML = '<div class="grid grid-cols-1 md:grid-cols-2 gap-4">' + subs.map(subjectCard).join('') + '</div>';
            bindGoLinks(root); // 含 data-gopoint 直达按钮（u10 已改落点：直达 knowledge_point 详情页）
        }).catch(function (err) {
            main.innerHTML = '<p class="text-sm text-cl-danger py-6">统计加载失败：' + esc(err.message) + '</p>';
        });
    }

    // ---------------- u10：知识点详情直达页 ----------------
    // 页面 cid → 中文名（面包屑用，与 sidebar/菜单文案对齐）
    var PAGE_NAMES = {
        dashboard: '工作台', online_course_notes: '网课笔记',
        practice_overview: '练·科目总览', practice_materials: '知识脑图',
        practice_knowledge: '从知识点练', practice_errors: '错题练习',
        memory_overview: '记·科目总览', memory_knowledge: '记知识点',
        memory_errors: '记错题', knowledge_point: '知识点详情',
        knowledge_base: '知识库', settings: '设置'
    };
    function crumbName(cid) { return PAGE_NAMES[cid] || cid; }
    // 桥 as:'json' 返回 JSON 字符串（api.js bridgeFn 约定），统一防御解析
    function parseBridge(s) { try { var v = JSON.parse(s); return v && typeof v === 'object' ? v : { success: false, error: '返回格式异常' }; } catch (e) { return { success: false, error: '返回解析失败' }; } }

    function bootKnowledgePoint(root) {
        var crumb = root.querySelector('#kp-crumb');
        var main = root.querySelector('[data-role="main"]');

        // —— 消费直达旗标（练/记总览、选点页写入；过期丢弃） ——
        var pending = null;
        try {
            var raw = localStorage.getItem('pm_pending_point');
            if (raw) {
                localStorage.removeItem('pm_pending_point');
                var pt = JSON.parse(raw);
                if (pt && pt.id && Date.now() - (pt.ts || 0) <= 10000) pending = pt;
            }
        } catch (e) { /* 旗标损坏不影响主流程 */ }
        // u10 CodeReview M-1：连点「去练习」会触发二次片段注入，旗标已被首次 boot 消费，
        // 若无幂等记录第二次 boot 会用空态覆盖详情页破坏直达契约 → 10s 内沿用最近消费记录
        if (!pending && global.__kpLastConsumed && Date.now() - (global.__kpLastConsumed.ts || 0) <= 10000) {
            pending = global.__kpLastConsumed;
        }
        if (pending) global.__kpLastConsumed = { id: pending.id, name: pending.name, ts: Date.now() };

        // —— 动态面包屑：按 SPA 导航轨迹如实还原用户点进来的路径（去掉详情页自身） ——
        function renderCrumb(pointName) {
            var path = [];
            (global.__pmTrail || []).forEach(function (c) { if (c !== 'knowledge_point' && path[path.length - 1] !== c) path.push(c); });
            path = path.slice(-3);
            if (!path.length) path = ['dashboard'];
            var sep = '<span class="text-cl-text-3">' + icon('chevron-right', 'w-3.5 h-3.5') + '</span>';
            var h = '';
            path.forEach(function (c, i) {
                if (i) h += sep;
                h += '<button class="hover:text-cl-primary cursor-pointer transition-colors" data-crumb="' + esc(c) + '">' + esc(crumbName(c)) + '</button>';
            });
            if (pointName) h += sep + '<span class="text-cl-text font-semibold">' + esc(pointName) + '</span>';
            crumb.innerHTML = h;
            crumb.querySelectorAll('[data-crumb]').forEach(function (b) {
                b.addEventListener('click', function () {
                    // 回退到轨迹中某页：截断其后的记录，避免来回路径污染面包屑
                    var t = global.__pmTrail || [];
                    var idx = t.lastIndexOf(b.getAttribute('data-crumb'));
                    if (idx >= 0) global.__pmTrail = t.slice(0, idx + 1);
                    goMenu(b.getAttribute('data-crumb'));
                });
            });
            // 窄栏高亮归组：按来源页所属模块点亮（学/练/记）
            try {
                if (typeof global.setActiveMenuItem === 'function') {
                    var last = path[path.length - 1];
                    if (/^practice/.test(last)) global.setActiveMenuItem('practice_overview');
                    else if (/^memory/.test(last)) global.setActiveMenuItem('memory_overview');
                    else global.setActiveMenuItem(last);
                }
            } catch (e) { /* noop */ }
        }

        if (!pending) {
            renderCrumb('');
            main.innerHTML = emptyBox('没有选定知识点', '请从练习或记忆总览中选择要巩固的知识点', '去练习总览', 'practice_overview');
            bindGoLinks(root);
            return;
        }
        renderCrumb(pending.name || '知识点详情');
        var pid = String(pending.id);
        var state = { det: null };
        var descGen = 0; // P3 评审：收起面板作废旧 assist 回包（与 prac.gen 同模式）
        var descEd = null; // 描述 Vditor 编辑器实例（用户验收 2026-10-08 方案A），随 renderAll 重建
        var descObs = null; // 编辑区内图片增量水合的观察器

        function statCell(ic, cls, n, label) {
            return '<div class="flex items-center gap-3 rounded-clbtn bg-cl-bg px-3 py-2">'
                + '<span class="' + cls + '">' + icon(ic, 'w-4 h-4') + '</span>'
                + '<p class="text-[13px] text-cl-text-2"><strong class="text-cl-text">' + esc(String(n == null ? 0 : n)) + '</strong> ' + label + '</p></div>';
        }

        // —— 主体：详情 + 动作 + 面板 + 最近练习 ——
        function renderAll(det) {
            state.det = det;
            descEdTearDown(); // 整页重建：旧编辑器 DOM 即将被替换，先销毁实例与观察器
            var h = '<div class="cl-card p-6">';
            h += '<div class="flex items-start justify-between gap-4 flex-wrap">';
            h += '<div class="min-w-0"><h1 class="text-xl font-bold text-cl-text break-words">' + esc(det.name) + '</h1>';
            h += '<div class="flex items-center gap-3 mt-2 text-xs text-cl-text-2 flex-wrap">'
                + '<span class="cl-badge bg-cl-primary-soft text-cl-primary">' + esc(det.subject_name || '未分学科') + '</span>'
                + '<span data-role="mastery-slot">' + masteryBadge(det.mastery_score) + '</span>'
                + '<span>创建于 ' + esc(relTime(det.created_time)) + '</span></div></div>';
            h += '<div class="w-44 shrink-0 mt-2 md:mt-0"><div class="text-[11px] text-cl-text-3 mb-1 text-right">熟练度</div>'
                + '<span data-role="progress-slot">' + progressBar(det.mastery_score) + '</span></div>';
            h += '</div>';
            // P3 描述编辑四方式：展示行 + 编辑入口 + 页内编辑面板
            h += '<div class="flex items-start justify-between gap-3 mt-4">';
            h += '<div data-role="desc-text" class="desc-md text-sm text-cl-text-2 leading-relaxed min-w-0 break-words flex-1"></div>';
            h += '<button class="cl-btn-ghost !h-7 text-[11px] shrink-0" data-role="desc-edit-btn">' + icon('sparkles', 'w-3.5 h-3.5') + ' 编辑描述</button></div>';
            h += '<div data-role="desc-edit-panel" class="hidden mt-3 rounded-clbtn bg-cl-bg px-4 py-3">'
                + '<div data-role="desc-editor"></div>'
                + '<div data-role="desc-preview" class="desc-md hidden bg-white rounded-clbtn border border-cl-border px-3 py-2 min-h-[160px] text-sm"></div>'
                + '<div class="flex items-center gap-2 mt-2 flex-wrap">'
                + '<button class="cl-btn-primary !h-8 text-xs" data-desc="save">保存</button>'
                + '<button class="cl-btn-ghost !h-8 text-xs" data-desc="preview">预览</button>'
                + '<button class="cl-btn-ghost !h-8 text-xs" data-desc="generate">' + icon('sparkles', 'w-3.5 h-3.5') + ' 大模型生成</button>'
                + '<button class="cl-btn-ghost !h-8 text-xs" data-desc="extract">' + icon('file-text', 'w-3.5 h-3.5') + ' 从关联笔记摘取</button>'
                + '<button class="cl-btn-ghost !h-8 text-xs" data-desc="polish">' + icon('lightbulb', 'w-3.5 h-3.5') + ' 整理描述</button>'
                + '<button class="cl-btn-ghost !h-8 text-xs" data-desc="cancel">收起</button>'
                + '<span data-role="desc-hint" class="text-xs text-cl-text-3"></span></div>'
                + '<p class="text-[11px] text-cl-text-3 mt-2">提示：编辑像 Obsidian 一样即时渲染（# 标题、- 列表、**加粗**），截图可直接 Ctrl+V 粘贴或拖入（自动存入笔记库「截图/」文件夹）；描述参与「题目→知识点」自动匹配，保存后匹配口径随之更新。</p></div>';
            h += '<div class="grid grid-cols-1 sm:grid-cols-3 gap-3 mt-5 pt-5 border-t border-cl-border">';
            h += statCell('alert-circle', 'text-cl-danger', det.error_count, '道错题') + statCell('target', 'text-cl-secondary', det.favorite_count, '个收藏题') + statCell('file-text', 'text-cl-primary', det.notes_count, '篇关联笔记');
            h += '</div></div>';
            // 动作区：熟练度评估/基于笔记练习页内闭环；举一反三移至「关联题目」区块头（P1 落地页统一，用户要求）
            h += '<div class="cl-card p-4 flex items-center gap-3 flex-wrap">';
            h += '<button class="cl-btn-primary !h-9 text-xs" data-act="assess">' + icon('sparkles', 'w-4 h-4') + ' 熟练度评估</button>';
            h += '<button class="cl-btn-ghost !h-9 text-xs" data-act="notes">' + icon('book-open', 'w-4 h-4') + ' 基于笔记练习</button>';
            h += '<span data-role="act-hint" class="text-xs text-cl-text-3"></span></div>';
            // c3：记忆数据面板（曲线+星值+手动熟练度），详情页默认展开
            h += '<div class="cl-card p-6" data-mw-root>' + memoryPanelHtml() + '</div>';
            h += '<div data-role="assess-panel" class="cl-card p-6 hidden"></div>';
            h += '<div data-role="practice-panel" class="cl-card p-6 hidden"></div>';
            h += '<div class="cl-card p-5"><div class="cl-section-title mb-3">' + icon('history', 'w-4 h-4 text-cl-primary') + ' 最近练习</div>';
            var rp = det.recent_practices || [];
            if (rp.length) {
                h += '<div class="space-y-2">' + rp.map(function (r) {
                    return '<div class="flex items-start gap-2 rounded-clbtn bg-cl-bg px-3 py-2">'
                        + (r.is_correct ? '<span class="cl-badge bg-cl-secondary-soft text-cl-secondary shrink-0">' + icon('check', 'w-3.5 h-3.5') + ' 正确</span>'
                            : '<span class="cl-badge bg-cl-danger-soft text-cl-danger shrink-0">' + icon('x', 'w-3.5 h-3.5') + ' 错误</span>')
                        + '<p class="text-[13px] text-cl-text flex-1 min-w-0 break-words">' + esc(truncate(r.question, 60)) + '</p>'
                        + '<span class="text-[11px] text-cl-text-3 shrink-0">' + esc(relTime(r.time)) + '</span></div>';
                }).join('') + '</div>';
            } else {
                h += '<p class="text-xs text-cl-text-3">还没有练习记录，先来一次熟练度评估吧</p>';
            }
            h += '</div>';
            // —— 关联笔记 / 关联题目区块（P1 落地页统一改造：原脑图抽屉信息并入本页，列表异步加载） ——
            h += '<div class="cl-card p-5"><div class="cl-section-title mb-3">' + icon('book-open', 'w-4 h-4 text-cl-primary') + ' 关联笔记'
                + '<span class="ml-2 text-[11px] font-normal text-cl-text-3">共 <span data-role="notes-count">-</span> 篇</span></div>';
            h += '<div data-role="notes-list" class="text-xs text-cl-text-3">正在加载关联笔记…</div></div>';
            h += '<div class="cl-card p-5"><div class="flex items-center justify-between gap-3 flex-wrap mb-3">';
            h += '<div class="cl-section-title">' + icon('target', 'w-4 h-4 text-cl-primary') + ' 关联题目'
                + '<span class="ml-2 text-[11px] font-normal text-cl-text-3">共 <span data-role="questions-count">-</span> 题</span></div>';
            h += '<div class="flex items-center gap-2 shrink-0">'
                + '<button class="cl-btn-ghost !h-9 text-xs" data-act="errprac">' + icon('dumbbell', 'w-4 h-4') + ' 错题练习</button>'
                + '<button class="cl-btn-ghost !h-9 text-xs" data-act="analogy">' + icon('lightbulb', 'w-4 h-4') + ' 举一反三练习</button></div>';
            h += '<div data-role="questions-list" class="text-xs text-cl-text-3">正在加载关联题目…</div></div>';
            main.innerHTML = h;
            main.querySelectorAll('[data-act]').forEach(function (b) {
                b.addEventListener('click', function () {
                    var act = b.getAttribute('data-act');
                    if (act === 'assess') startAssess(b);
                    else if (act === 'notes') startNotePractice(b);
                    else if (act === 'errprac') openPracticeChooser('error');
                    else openPracticeChooser('analogy'); // P5：举一反三改为智能/手动模式弹窗
                });
            });
            mountMemoryWidgets(main, 'kp', pid); // 每次整页重渲染后重新挂载取最新曲线/星值
            bindDescEdit(); // P3 描述编辑（Vditor）
            renderDescView(); // 描述按 MD 渲染（含图片水合）
            loadLinkedNotes();
            loadLinkedQuestions();
        }

        // —— P3 描述编辑：手动输入 / 大模型生成 / 笔记关键字摘取（无 LLM）/ LLM 整理 ——
        function descHint(msg, isErr) {
            var el = main.querySelector('[data-role="desc-hint"]');
            if (el) el.innerHTML = isErr ? '<span class="text-cl-danger">' + esc(msg) + '</span>' : esc(msg);
        }
        function bindDescEdit() {
            var btn = main.querySelector('[data-role="desc-edit-btn"]');
            var panel = main.querySelector('[data-role="desc-edit-panel"]');
            if (!btn || !panel) return;
            descPreviewOn = false; // 面板随整页重建，切换状态复位
            btn.addEventListener('click', function () {
                panel.classList.remove('hidden');
                if (!descEd) descEdCreate(panel.querySelector('[data-role="desc-editor"]'), (state.det && state.det.description) || '');
                // 再次打开：编辑器仍空则回填当前描述（与旧 textarea 口径一致）
                else if (!descEdGetValue()) descEdSetValue((state.det && state.det.description) || '');
                descEdFocus();
            });
            panel.querySelectorAll('[data-desc]').forEach(function (b) {
                b.addEventListener('click', function () {
                    var act = b.getAttribute('data-desc');
                    if (act === 'cancel') {
                        descGen++; // 作废在途 assist 回写
                        panel.querySelectorAll('[data-desc]').forEach(function (x) { x.disabled = false; }); // 回包已不会恢复，此处兼作释放
                        panel.classList.add('hidden'); descHint(''); return;
                    }
                    if (act === 'save') { saveDesc(b); return; }
                    if (act === 'preview') { toggleDescPreview(b, panel); return; }
                    descAssist(act, b);
                });
            });
        }
        var descPreviewOn = false; // 面板内「预览/编辑」切换态（用户验收 2026-10-08）
        function toggleDescPreview(b, panel) {
            var mount = panel.querySelector('[data-role="desc-editor"]');
            var pv = panel.querySelector('[data-role="desc-preview"]');
            if (!pv || !mount) return;
            if (!descEd || descEd.mode === 'vditor' && !descEd.ready) { descHint('编辑器加载中，请稍候再预览'); return; }
            descPreviewOn = !descPreviewOn;
            if (descPreviewOn) {
                pv.classList.add('desc-md');
                renderMdInto(pv, descEdGetValue(), null);
                mount.classList.add('hidden'); pv.classList.remove('hidden');
                b.textContent = '返回编辑';
            } else {
                pv.classList.add('hidden'); mount.classList.remove('hidden');
                b.textContent = '预览';
            }
        }
        function saveDesc(btn) {
            btn.disabled = true; descHint('正在保存…');
            function fail(msg) { descHint(msg, true); btn.disabled = false; }
            if (descEd && descEd.mode === 'vditor' && !descEd.ready) { fail('编辑器还在加载，请稍后再保存'); return; }
            var md = descEdGetValue();
            if (/data:image/i.test(md)) { fail('图片尚未上传完成，稍后再试'); return; }
            if (md.length > 5000) { fail('描述超过 5000 字（当前 ' + md.length + ' 字），请精简后再保存'); return; }
            sendJSON('PUT', '/api/knowledge/points/' + encodeURIComponent(pid) + '/description', { description: md })
                .then(function (d) {
                    if (!guard(main)) return;
                    if (d.success !== true) throw new Error(d.error || '保存失败');
                    state.det.description = d.core_description;
                    renderDescView();
                    descHint('已保存');
                }).catch(function (e) { if (guard(main)) descHint(e.message, true); })
                .then(function () { btn.disabled = false; });
        }
        function descAssist(action, btn) {
            if (!descEd || descEd.mode === 'vditor' && !descEd.ready) { descHint('编辑器还在加载，请稍候再试'); return; }
            var myGen = ++descGen;
            var others = btn.parentElement.querySelectorAll('[data-desc]');
            others.forEach(function (x) { if (x.getAttribute('data-desc') !== 'cancel') x.disabled = true; });
            descHint(action === 'extract' ? '正在从关联笔记摘取…' : 'AI 处理中，预计需要几十秒…');
            // 评审 Minor：脚本赋值不受 maxlength 约束，统一限 5000 与后端 PUT 口径一致
            function setTa(text) {
                var over = text.length > 5000;
                descEdSetValue(over ? text.slice(0, 5000) : text);
                return over;
            }
            postJSON('/api/knowledge/points/' + encodeURIComponent(pid) + '/description-assist',
                { action: action, description: descEdGetValue() })
                .then(function (d) {
                    if (!guard(main) || descGen !== myGen) return; // 已收起/重开→作废回写
                    if (d.success !== true) {
                        throw new Error(d.credits_insufficient ? '积分不足，请充值后使用 AI 功能' : (d.error || '处理失败'));
                    }
                    var truncated = false;
                    if (action === 'extract') {
                        // 摘取忠实原文：追加到编辑器，不覆盖已有内容
                        var curVal = descEdGetValue().trim();
                        truncated = setTa((curVal ? curVal + '\n\n' : '') + d.text);
                        descHint(truncated ? '摘取内容超长已截断至 5000 字，请审阅后保存' : '已从笔记摘取相关段落并追加，请审阅后保存');
                    } else {
                        var curVal2 = descEdGetValue().trim();
                        if (curVal2 && !window.confirm('用' + (action === 'generate' ? '生成' : '整理后') + '的描述替换编辑器当前内容？选择取消则追加到末尾。')) {
                            truncated = setTa(curVal2 + '\n\n' + d.text);
                            descHint(truncated ? '追加超长已截断至 5000 字' : '已追加到末尾（未覆盖原内容），请编辑后保存');
                        } else {
                            truncated = setTa(d.text);
                            descHint((action === 'generate' ? '生成完成' : '整理完成') + (truncated ? '（超长已截断至 5000 字）' : '，请审阅后保存'));
                        }
                        descEdFocus();
                    }
                }).catch(function (e) { if (guard(main) && descGen === myGen) descHint(e.message, true); })
                .then(function () { if (descGen === myGen) others.forEach(function (x) { x.disabled = false; }); });
        }

        // —— 描述 Vditor 编辑器（用户验收 2026-10-08 方案A）：类 Obsidian 即时渲染 + 粘贴/拖图上传存 vault「截图/」 ——
        // 4.0.0 压缩包探针实证：upload.handler 拦截粘贴文件（返回字符串即报错提示），无 insertImage，
        // 用 insertMD 插入；自定义上传完成后需手动复位 upload.isUploading。脚本缺失时回退纯 textarea。
        function descEdTearDown() {
            if (descObs) { try { descObs.disconnect(); } catch (e) { /* noop */ } descObs = null; }
            if (descEd) {
                if (descEd.vd) { try { descEd.vd.destroy(); } catch (e) { /* noop */ } }
                descEd = null;
            }
        }
        function descEdCreate(mountEl, initValue) {
            if (!mountEl || descEd) return descEd;
            if (window.Vditor) {
                var vd = new window.Vditor(mountEl, {
                    cdn: '/static/vendor/vditor',
                    mode: 'ir',
                    // Vditor 4.0 校验白名单为下划线格式（zh_CN），传 zh-CN 会在构造函数直接抛 options.lang error
                    lang: 'zh_CN',
                    icon: 'material',
                    height: 320,
                    value: initValue || '',
                    placeholder: '支持 Markdown 语法；截图可直接 Ctrl+V 粘贴或拖入',
                    cache: { enable: false },
                    toolbarConfig: { pin: true },
                    toolbar: ['headings', 'bold', 'italic', 'strike', '|', 'list', 'ordered-list', 'check', 'quote', 'code', 'inline-code', 'link', 'table', 'line', '|', 'undo', 'redo'],
                    preview: { hljs: { style: 'github', lineNumber: false } },
                    upload: {
                        accept: 'image/*',
                        handler: function (files) {
                            // 评审 m2：多文件并发时计数器归零才复位 isUploading，防首张完成即禁入失效
                            var left = files.length;
                            var oneDone = function () {
                                left--;
                                if (left <= 0) { try { vd.vditor.upload.isUploading = false; } catch (e) { /* noop */ } }
                            };
                            for (var i = 0; i < files.length; i++) descUploadImage(vd, files[i], oneDone);
                            return null; // 异步上传；错误已经 descHint 呈现
                        }
                    },
                    after: function () { if (descEd) descEd.ready = true; }
                });
                descEd = { mode: 'vditor', mount: mountEl, vd: vd, ready: false };
                mountEl.__vd = vd; // 调试/CDP 断言入口：Vditor 4 不再挂 window.vditor，实例留挂载体上
            } else {
                var ta2 = document.createElement('textarea');
                ta2.rows = 8;
                ta2.placeholder = '支持 Markdown 语法（编辑器脚本未加载，已回退纯文本模式，暂不支持贴图）';
                ta2.className = 'w-full rounded-clbtn border border-cl-border px-3 py-2 text-sm text-cl-text focus:outline-none focus:border-cl-primary';
                ta2.value = initValue || '';
                mountEl.appendChild(ta2);
                descEd = { mode: 'textarea', mount: mountEl, ta: ta2, ready: true };
            }
            // 编辑区内图片（相对/绝对路径无法直载）走笔记同款 base64 管线；观察器覆盖持续重渲染
            if (window.MutationObserver) {
                descObs = new MutationObserver(function () { if (descEd) descHydrateImgs(descEd.mount); });
                descObs.observe(mountEl, { childList: true, subtree: true, attributes: true, attributeFilter: ['src'] });
            }
            return descEd;
        }
        function descHydrateImgs(mount) {
            if (!mount || !window.pybridge || !window.pybridge.getImageAsBase64) return;
            mount.querySelectorAll('img').forEach(function (img) {
                var src = img.getAttribute('src') || '';
                if (!src || img.getAttribute('data-vd-hy')) return;
                img.setAttribute('data-vd-hy', '1');
                if (/^(data:|blob:|https?:)/i.test(src)) return; // base64/外链保持原样
                img.setAttribute('data-vd-src', src); // 存原始引用：保存时据此换回，禁 base64 入库
                img.setAttribute('src', NB_IMG_PH);
                var p = src;
                try { p = decodeURIComponent(src); } catch (e) { /* 非法编码保留原串 */ }
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
        // 取编辑器 MD：先把水合过的 base64 换回原始路径再 getValue，保证入库的是引用而非巨串；
        // 评审 M1（2026-10-08）：读完后同 tick 立即换回 base64 保持显示（观察器 data-vd-hy 短路不会自动补回）
        function descEdGetValue() {
            if (!descEd) return '';
            if (descEd.mode === 'textarea') return descEd.ta.value;
            var restore = [];
            descEd.mount.querySelectorAll('img[data-vd-src]').forEach(function (im) {
                var cur = im.getAttribute('src') || '';
                if (/^data:/i.test(cur)) {
                    restore.push([im, cur]);
                    im.setAttribute('src', im.getAttribute('data-vd-src'));
                }
            });
            var md = '';
            try { md = descEd.vd.getValue() || ''; } catch (e) { md = ''; }
            restore.forEach(function (p) { try { p[0].setAttribute('src', p[1]); } catch (e) { /* noop */ } });
            return md;
        }
        function descEdSetValue(text) {
            if (!descEd) return;
            if (descEd.mode === 'textarea') { descEd.ta.value = text; return; }
            try { descEd.vd.setValue(text); } catch (e) { /* noop */ }
        }
        function descEdFocus() {
            if (!descEd) return;
            if (descEd.mode === 'textarea') { descEd.ta.focus(); return; }
            try { descEd.vd.focus(); } catch (e) { /* noop */ }
        }
        function descUploadImage(vd, file, done) {
            var finish = function () { if (done) done(); else { try { vd.vditor.upload.isUploading = false; } catch (e) { /* noop */ } } };
            if (!file || !/^image\//i.test(file.type || '')) { descHint('仅支持粘贴/插入图片', true); finish(); return; }
            var fr = new FileReader();
            fr.onload = function () {
                var b64 = String(fr.result || '').split(',')[1] || '';
                // name 带毫秒：后端同名直接覆盖，避免连续粘贴互毁（悬浮窗端点复用，零后端改动）
                postJSON('/api/vault/screenshot', { image_b64: b64, name: 'desc_' + Date.now() + '.png' })
                    .then(function (d) {
                        if (!d || d.success !== true || !d.rel) throw new Error((d && d.error) || '截图保存失败');
                        try { vd.insertMD('![图片](' + d.rel + ')'); } catch (e) { /* noop */ }
                        descHint('截图已插入描述，点保存后生效');
                    })
                    .catch(function (e) { descHint('图片插入失败：' + e.message, true); })
                    .then(finish);
            };
            fr.onerror = function () { descHint('读取图片数据失败', true); finish(); };
            fr.readAsDataURL(file);
        }
        function renderDescView() {
            var t = main.querySelector('[data-role="desc-text"]');
            if (!t) return;
            var raw = (state.det && state.det.description) || '';
            if (!raw) {
                t.innerHTML = '<span class="text-cl-text-3">还没有核心描述，点右侧「编辑描述」手动输入、AI 生成或从笔记摘取。</span>';
                return;
            }
            if (!renderMdInto(t, raw, null)) t.classList.add('whitespace-pre-wrap');
        }
        // 共享 MD 渲染管线（笔记浏览/描述展示/描述预览三处统一）：Obsidian 图预处理 → marked → 清洗 → 图片水合
        function renderMdInto(el, src, filePath) {
            if (typeof marked === 'undefined' || !marked.parse) {
                el.textContent = src || '';
                return false; // 纯文本回退，调用方自行加 whitespace-pre-wrap
            }
            var srcMd = (src || '').replace(/!\[\[([^\]]+)\]\]/g, function (m, fn) {
                var pure = String(fn).split('/').pop().split('\\').pop();
                return '![' + pure + '](attachments/' + pure + ')';
            });
            var rawHtml = marked.parse(srcMd);
            el.innerHTML = (typeof window.DOMPurify !== 'undefined' && window.DOMPurify.sanitize)
                ? window.DOMPurify.sanitize(rawHtml) : rawHtml;
            hydrateNoteImages(el, filePath);
            return true;
        }

        // —— 关联笔记列表（P4：卡片可点开完整 MD 预览弹层） ——
        function loadLinkedNotes() {
            var box = main.querySelector('[data-role="notes-list"]');
            if (!box) return;
            getJSON('/api/knowledge/points/' + encodeURIComponent(pid) + '/notes').then(function (d) {
                if (!guard(box)) return;
                var notes = (d && d.notes) || [];
                state.notes = notes;
                var cnt = main.querySelector('[data-role="notes-count"]');
                if (cnt) cnt.textContent = String(notes.length);
                if (!notes.length) { box.innerHTML = '<p class="text-xs text-cl-text-3">还没有关联笔记，可先到「学」页学习并提取知识点笔记</p>'; return; }
                box.innerHTML = '<div class="grid grid-cols-1 sm:grid-cols-2 gap-3">' + notes.map(function (n, i) {
                    return '<div class="rounded-clbtn bg-cl-bg px-3 py-2 border border-transparent hover:border-cl-primary transition-colors cursor-pointer" data-note-open="' + i + '" title="点击进入笔记浏览视图">'
                        + '<p class="text-[13px] font-medium text-cl-text break-words">' + icon('file-text', 'w-3.5 h-3.5 text-cl-primary inline mr-1') + esc(n.title || '未命名笔记') + '</p>'
                        + '<p class="text-[11px] text-cl-text-3 mt-1">更新于 ' + esc(relTime(n.updated_time))
                        + (n.extraction_time ? ' · 关联于 ' + esc(relTime(n.extraction_time)) : '') + '</p>'
                        + '<p class="text-[11px] text-cl-primary mt-1">浏览全文 · 定位知识点 · 摘取选段</p></div>';
                }).join('') + '</div>';
                box.querySelectorAll('[data-note-open]').forEach(function (c) {
                    c.addEventListener('click', function () { openNoteBrowser(Number(c.getAttribute('data-note-open'))); });
                });
            }).catch(function (e) {
                if (!guard(box)) return;
                box.innerHTML = '<p class="text-xs text-cl-danger">关联笔记加载失败：' + esc(e.message) + '</p>';
            });
        }

        // —— P4 笔记浏览视图（2026-10-10 用户验收反馈：原全屏弹层改为与「学」页同款的页内分栏视图：
        // 左列=关联笔记清单（像文件栏一样可切换），中间=完整 MD 预览，右列=本篇笔记的知识点（点击定位高亮），
        // 选段摘取悬浮按钮逻辑复用；「返回知识点」重渲染回落地页 ——
        var pickDismiss = null; // P4 评审 m-4：dismiss 句柄登记，hidePickBtn 统一摘除
        var nbIdx = -1; // 当前打开的笔记下标（-1=不在浏览视图）
        function openNoteBrowser(i) { nbIdx = i; renderNoteBrowser(); }
        function closeNoteBrowser() {
            nbIdx = -1;
            hidePickBtn();
            root.classList.remove('!max-w-none'); // 恢复落地页 1120px 居中版心
            renderAll(state.det); // 整页重建：记忆 widgets/描述面板/列表重新初始化（与既有重渲染口径一致）
        }
        function renderNoteBrowser() {
            descEdTearDown(); // 离开落地页：描述编辑器随旧 DOM 销毁（笔记浏览视图共用 main 容器）
            var notes = state.notes || [];
            var n = notes[nbIdx];
            if (!n) { closeNoteBrowser(); return; }
            hidePickBtn();
            nbHl = { kw: null, els: [], idx: -1 }; // 切篇/重进：定位循环状态作废（旧 mark 随 DOM 重建消失）
            root.classList.add('!max-w-none'); // 用户验收反馈：浏览视图铺满全宽，不再挤在 1120px 版心
            var h = '<div class="flex items-center justify-between gap-3 flex-wrap">'
                + '<div class="flex items-center gap-3 min-w-0">'
                + '<button class="cl-btn-ghost !h-8 text-xs shrink-0" data-role="nb-back">' + icon('chevron-left', 'w-4 h-4') + ' 返回知识点</button>'
                + '<div class="cl-section-title min-w-0">' + icon('file-text', 'w-4 h-4 text-cl-primary') + ' <span class="break-words">' + esc(n.title || '未命名笔记') + '</span>'
                + '<span class="ml-2 text-[11px] font-normal text-cl-text-3" data-role="nb-meta"></span></div></div>'
                + '<span class="text-[11px] text-cl-text-3 shrink-0">共 ' + notes.length + ' 篇关联笔记</span></div>';
            h += '<div class="flex gap-4 mt-3 h-[calc(100vh-230px)] min-h-[320px]">'
                + '<div class="w-44 shrink-0 overflow-y-auto border-r border-cl-border pr-2">'
                + '<p class="text-xs font-semibold text-cl-text-2 mb-2">关联笔记（点击切换）</p>'
                + '<div class="space-y-1">' + notes.map(function (x, i) {
                    return '<button class="block w-full text-left text-[13px] rounded-clbtn px-2 py-1.5 break-words ' + (i === nbIdx ? 'bg-cl-primary-soft text-cl-primary font-medium' : 'bg-cl-bg text-cl-text-2 hover:text-cl-primary') + '" data-nb-open="' + i + '">' + esc(x.title || '未命名笔记') + '</button>';
                }).join('') + '</div></div>'
                + '<div data-role="nb-md" class="flex-1 min-w-0 overflow-y-auto rounded-clbtn bg-cl-bg px-4 py-3 text-sm leading-relaxed"><p class="text-cl-text-3 py-8 text-center">正在加载笔记全文…</p></div>'
                + '<div class="w-60 shrink-0 overflow-y-auto">'
                + '<p class="text-xs font-semibold text-cl-text-2 mb-2">本篇笔记的知识点（点击定位）</p>'
                + '<div data-role="nb-kps" class="space-y-1"><p class="text-xs text-cl-text-3">加载中…</p></div>'
                + '<p data-role="nb-locate-hint" class="text-[11px] text-cl-text-3 mt-2"></p>'
                + '<p class="text-[11px] text-cl-text-3 mt-4 pt-3 border-t border-cl-border">提示：在正文中选中文字后会出现悬浮按钮，可把选段追加到本知识点描述。</p>'
                + '<p data-role="nb-pick-hint" class="text-[11px] mt-1"></p>'
                + '</div></div>';
            main.innerHTML = h;
            main.querySelector('[data-role="nb-back"]').addEventListener('click', closeNoteBrowser);
            main.querySelectorAll('[data-nb-open]').forEach(function (b) {
                b.addEventListener('click', function () { openNoteBrowser(Number(b.getAttribute('data-nb-open'))); });
            });
            var md = main.querySelector('[data-role="nb-md"]');
            getJSON('/api/notes/' + encodeURIComponent(n.id) + '/content').then(function (d) {
                if (!md.isConnected) return; // 已切篇/已返回 → 旧回包丢弃
                if (!d || d.success !== true) throw new Error((d && d.error) || '笔记加载失败');
                var note = d.note;
                var meta = main.querySelector('[data-role="nb-meta"]');
                if (meta) meta.textContent = '全文 ' + (note.content_length || 0) + ' 字';
                // 与「学」页同一渲染管线（已抽公共函数 renderMdInto）：Obsidian ![[图片]] → 标准 MD → marked → DOMPurify → 桥转 base64
                if (!renderMdInto(md, note.content || '', note.file_path)) {
                    md.classList.add('whitespace-pre-wrap'); // marked 缺失时纯文本回退（与旧口径一致）
                }
                var kpBox = main.querySelector('[data-role="nb-kps"]');
                if (kpBox) {
                    kpBox.innerHTML = (note.related_knowledge_points || []).map(function (k) {
                        return '<button class="block w-full text-left text-[13px] rounded-clbtn bg-cl-bg px-2 py-1.5 text-cl-text-2 hover:text-cl-primary break-words" data-kp-locate="' + esc(k.name) + '">' + icon('search', 'w-3.5 h-3.5 inline') + ' ' + esc(k.name) + '</button>';
                    }).join('') || '<p class="text-xs text-cl-text-3">暂无关联知识点</p>';
                    kpBox.querySelectorAll('[data-kp-locate]').forEach(function (b) {
                        b.addEventListener('click', function () {
                            var r = locateKpText(md, b.getAttribute('data-kp-locate'));
                            var el = main.querySelector('[data-role="nb-locate-hint"]');
                            if (el) el.textContent = r ? '已定位第 ' + (r.idx + 1) + ' / ' + r.total + ' 处，再点跳下一处' : '正文中未找到该词';
                        });
                    });
                }
                md.addEventListener('mouseup', function () { onNoteSelection(md); });
            }).catch(function (e) {
                if (md.isConnected) md.innerHTML = '<p class="text-sm text-cl-danger py-6">笔记加载失败：' + esc(e.message) + '</p>';
            });
        }
        // 「学」页同款图片解析（resolveNoteImgSrc）：相对路径按所在笔记目录拼成 vault 绝对路径；外链/data/绝对形态放行
        function resolveNbImgSrc(src, filePath) {
            if (!src) return null;
            if (/^(data:|https?:|blob:|\/)/i.test(src)) return null;
            try { src = decodeURIComponent(src); } catch (e) { /* 非法百分号编码，保留原串 */ }
            if (src.indexOf('attachments/') === 0) return src;
            // 粘贴截图落在 vault 根「截图/」保留目录（与学页 resolveNoteImgSrc 同步），根相对直送后端
            if (src.indexOf('截图/') === 0) return src;
            if (!filePath) return src;
            var sep = filePath.indexOf('\\') >= 0 ? '\\' : '/';
            var dir = filePath.replace(/[\\/][^\\/]*$/, '');
            if (dir === filePath) return src; // 笔记在 vault 根：根相对路径直送后端
            return dir + sep + src.replace(/[\\/]/g, sep);
        }
        var NB_IMG_PH = 'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMjAwIiBoZWlnaHQ9IjEwMCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cmVjdCB3aWR0aD0iMTAwJSIgaGVpZ2h0PSIxMDAlIiBmaWxsPSIjZjBmMGYwIi8+PHRleHQgeD0iNTAlIiB5PSI1MCUiIGZvbnQtZmFtaWx5PSJBcmlhbCIgZm9udC1zaXplPSIxNCIgZmlsbD0iIzk5OSIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZHk9Ii4zZW0iPuWKoOi9veS4rS4uLjwvdGV4dD48L3N2Zz4=';
        // 相对路径图片先占位，再走 pybridge.getImageAsBase64（/api/vault/image）异步换 base64（与「学」页同链路）
        function hydrateNoteImages(md, filePath) {
            if (!window.pybridge || !window.pybridge.getImageAsBase64) return;
            md.querySelectorAll('img').forEach(function (img) {
                var p = resolveNbImgSrc(img.getAttribute('src'), filePath);
                if (!p) return; // 外链/绝对路径保持原样直载
                img.setAttribute('data-nb-src', p); // 摘取时凭此拿可解析的原路径（验收 2026-10-08：摘取带图片）
                img.setAttribute('src', NB_IMG_PH);
                window.pybridge.getImageAsBase64(p, function (result) {
                    try {
                        var resp = JSON.parse(result);
                        if (!md.contains(img)) return; // 已切篇/已返回 → 回包丢弃
                        if (resp.success && resp.dataUrl) {
                            img.setAttribute('src', resp.dataUrl);
                            img.setAttribute('title', '图片: ' + p);
                        } else {
                            img.setAttribute('alt', '图片加载失败: ' + p);
                            img.setAttribute('title', resp.error || '图片加载失败');
                        }
                    } catch (e) { /* 解析失败保持占位 */ }
                });
            });
        }
        var nbHl = { kw: null, els: [], idx: -1 }; // 定位循环状态（「学」页 highlightAndLocateInNote 同款）
        function clearKpMarks(box) {
            box.querySelectorAll('mark[data-kp-hl]').forEach(function (m) {
                m.parentNode.replaceChild(document.createTextNode(m.textContent), m);
            });
            box.normalize();
            nbHl = { kw: null, els: [], idx: -1 };
        }
        // 全部命中包 <mark>，当前处深色激活并滚动居中；同一词再点循环跳到下一处。返回 {idx,total} 或 null
        function locateKpText(box, name) {
            if (nbHl.kw === name && nbHl.els.length) {
                nbHl.idx = (nbHl.idx + 1) % nbHl.els.length;
                activateKpHl();
                return { idx: nbHl.idx, total: nbHl.els.length };
            }
            clearKpMarks(box);
            if (!name) return null;
            var nodes = [];
            var walker = document.createTreeWalker(box, NodeFilter.SHOW_TEXT, null);
            for (var node; (node = walker.nextNode());) nodes.push(node);
            nodes.forEach(function (tn) {
                var text = tn.nodeValue;
                var i = text.indexOf(name);
                if (i < 0) return;
                var frag = document.createDocumentFragment();
                var last = 0;
                while (i >= 0) {
                    if (i > last) frag.appendChild(document.createTextNode(text.slice(last, i)));
                    var mk = document.createElement('mark');
                    mk.setAttribute('data-kp-hl', '1');
                    mk.className = 'nb-kp-hl';
                    mk.textContent = name;
                    frag.appendChild(mk);
                    last = i + name.length;
                    i = text.indexOf(name, last);
                }
                if (last < text.length) frag.appendChild(document.createTextNode(text.slice(last)));
                tn.parentNode.replaceChild(frag, tn);
            });
            nbHl.els = Array.prototype.slice.call(box.querySelectorAll('mark[data-kp-hl]'));
            if (!nbHl.els.length) return null;
            nbHl.kw = name;
            nbHl.idx = 0;
            activateKpHl();
            return { idx: 0, total: nbHl.els.length };
        }
        function activateKpHl() {
            nbHl.els.forEach(function (el, i) { el.classList.toggle('nb-kp-hl-active', i === nbHl.idx); });
            var cur = nbHl.els[nbHl.idx];
            if (cur) cur.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
        function hidePickBtn() {
            var b = document.querySelector('[data-role="note-pick-btn"]');
            if (b) b.remove();
            if (pickDismiss) { document.removeEventListener('mousedown', pickDismiss, true); pickDismiss = null; }
        }
        function onNoteSelection(md) {
            setTimeout(function () { // 等浏览器定框选区
                if (!guard(md)) return;
                var s = window.getSelection();
                var text = s ? String(s).trim() : '';
                if (!s || !s.rangeCount || !s.anchorNode || !md.contains(s.anchorNode)) { hidePickBtn(); return; }
                var frag = s.getRangeAt(0).cloneContents(); // 立即快照选区：含图片时连图一起摘（验收 2026-10-08）
                if (!text && !frag.querySelector('img')) { hidePickBtn(); return; }
                var rect = s.getRangeAt(0).getBoundingClientRect();
                hidePickBtn();
                var btn = document.createElement('button');
                btn.setAttribute('data-role', 'note-pick-btn');
                btn.className = 'fixed z-[70] cl-btn-primary !h-8 text-xs px-3';
                btn.style.left = Math.max(8, Math.min(rect.left, window.innerWidth - 200)) + 'px';
                btn.style.top = (rect.bottom + 8) + 'px';
                btn.textContent = '加入知识点描述';
                btn.addEventListener('mousedown', function (e) { e.preventDefault(); }); // 不抢焦点，保留选区
                btn.addEventListener('click', function () { pickAddDesc(selectionToMd(frag, text)); });
                document.body.appendChild(btn);
                // 点任意其它处即收起（也覆盖弹层开着直接切页的残留场景）；句柄登记供 hidePickBtn 统一摘除
                pickDismiss = function (e2) { if (btn.contains(e2.target)) return; hidePickBtn(); };
                setTimeout(function () { if (pickDismiss) document.addEventListener('mousedown', pickDismiss, true); }, 0);
            }, 0);
        }
        // 选区 DOM 片段 → Markdown：文本保真；图片转 ![...](原路径)（data-nb-src 是水合前的可解析路径，
        // 反斜杠归一为正斜杠避免 MD 链接目标转义；纯 base64 图不入库）。无结构化内容时回退纯选中文本
        function selectionToMd(frag, fallback) {
            var out = '';
            var BLOCK = { P: 1, DIV: 1, H1: 1, H2: 1, H3: 1, H4: 1, H5: 1, H6: 1, BLOCKQUOTE: 1, PRE: 1, TR: 1, UL: 1, OL: 1, TABLE: 1 };
            function nl() {
                if (!out) return;
                if (out.slice(-2) === String.fromCharCode(10, 10)) return;
                out += out.slice(-1) === String.fromCharCode(10) ? String.fromCharCode(10) : String.fromCharCode(10, 10);
            }
            function walk(node) {
                var kids = node.childNodes;
                for (var i = 0; i < kids.length; i++) {
                    var c = kids[i];
                    if (c.nodeType === 3) { out += c.textContent; continue; }
                    if (c.nodeType !== 1) continue;
                    var tag = c.tagName;
                    if (tag === 'IMG') {
                        var p = c.getAttribute('data-nb-src') || '';
                        if (!p) {
                            var src0 = c.getAttribute('src') || '';
                            if (/^https?:/i.test(src0)) p = src0; // 外链图保留 URL
                        }
                        if (p && !/^data:/i.test(p)) { nl(); out += '![](' + p.replace(/\\/g, '/') + ')'; nl(); }
                        continue;
                    }
                    if (tag === 'BR') { out += '\n'; continue; }
                    if (tag === 'LI') { nl(); out += '- '; walk(c); continue; }
                    if (BLOCK[tag]) { nl(); walk(c); nl(); continue; }
                    walk(c);
                }
            }
            try { walk(frag); } catch (e) { out = ''; }
            out = out.replace(/\n{3,}/g, '\n\n').trim();
            return out || (fallback || '').trim();
        }
        // 笔记浏览视图内的摘取反馈槽：该视图没有 act-hint/desc-hint，避免静默无反馈（与 nb-locate-hint 同款模式）
        function nbPickHint(msg, isErr) {
            var el = main.querySelector('[data-role="nb-pick-hint"]');
            if (el) { el.textContent = msg; el.className = 'text-[11px] mt-1 ' + (isErr ? 'text-cl-danger' : 'text-cl-primary'); }
        }
        // 选段（含图片引用）追加到本页知识点 core_description（与手动保存同 PUT 通道）
        function pickAddDesc(mdText) {
            hidePickBtn();
            // 摘取发生在笔记浏览视图，描述编辑器已随视图销毁；若仍在落地页且面板开着则同步草稿
            var base = ((state.det && state.det.description) || '').trim();
            if (descEd && descEd.mount.isConnected) { var draft = descEdGetValue().trim(); if (draft) base = draft; }
            var merged = (base ? base + '\n\n' : '') + mdText;
            var over = merged.length > 5000;
            if (over) merged = merged.slice(0, 5000);
            var myGen = ++descGen; // 与 assist 共用令牌：作废旧在途回写，防后到包覆盖新内容
            sendJSON('PUT', '/api/knowledge/points/' + encodeURIComponent(pid) + '/description', { description: merged })
                .then(function (d) {
                    if (!guard(main) || descGen !== myGen) return;
                    if (d.success !== true) throw new Error(d.error || '保存失败');
                    state.det.description = d.core_description;
                    if (descEd && descEd.mount.isConnected) descEdSetValue(d.core_description || '');
                    descHint(over ? '选段已追加，超长部分已截断至 5000 字，请审阅' : '已把选段（含图片）追加到描述');
                    hint(over ? '已把选段追加到描述（超长已截断至 5000 字）' : '已把选段（含图片）追加到描述，可点「编辑描述」审阅调整');
                    nbPickHint(over ? '已把选段追加到描述（超长已截断至 5000 字）' : '已把选段（含图片）追加到本知识点描述', false);
                }).catch(function (e) { if (guard(main) && descGen === myGen) { descHint('追加失败：' + e.message, true); hint('追加失败：' + e.message, true); nbPickHint('追加失败：' + e.message, true); } });
        }

        // —— 关联题目（P2 关联题目改造）：错题/非错题/全部筛选 + 前端分页 + 详情模态 + 单题练习 ——
        var QPAGE = 10;
        var qView = { all: [], tab: 'all', page: 1 };
        function isWrongQ(q) { return (q.practice_count || 0) - (q.correct_count || 0) > 0; }
        function loadLinkedQuestions() {
            var box = main.querySelector('[data-role="questions-list"]');
            if (!box) return;
            getJSON('/api/knowledge/points/' + encodeURIComponent(pid) + '/questions').then(function (d) {
                if (!guard(box)) return;
                qView.all = (d && d.questions) || [];
                var cnt = main.querySelector('[data-role="questions-count"]');
                if (cnt) cnt.textContent = String(qView.all.length);
                renderQuestions(); // 提交练习/评估后刷新时保留当前筛选页码（renderQuestions 内做 clamp）
            }).catch(function (e) {
                if (!guard(box)) return;
                box.innerHTML = '<p class="text-xs text-cl-danger">关联题目加载失败：' + esc(e.message) + '</p>';
            });
        }
        function renderQuestions() {
            var box = main.querySelector('[data-role="questions-list"]');
            if (!box) return;
            var all = qView.all;
            if (!all.length) { box.innerHTML = '<p class="text-xs text-cl-text-3">还没有关联题目，先做一轮练习即可产生题目留痕</p>'; return; }
            var nWrong = all.filter(isWrongQ).length;
            var list = all.filter(function (q) { return qView.tab === 'wrong' ? isWrongQ(q) : qView.tab === 'right' ? !isWrongQ(q) : true; });
            var pages = Math.max(1, Math.ceil(list.length / QPAGE));
            if (qView.page > pages) qView.page = pages;
            var slice = list.slice((qView.page - 1) * QPAGE, qView.page * QPAGE);
            var h = '<div class="flex items-center gap-2 mb-3 flex-wrap">' + [['wrong', '错题', nWrong], ['right', '非错题', all.length - nWrong], ['all', '全部', all.length]].map(function (t) {
                var on = qView.tab === t[0];
                return '<button class="cl-badge cursor-pointer transition-colors ' + (on ? 'bg-cl-primary-soft text-cl-primary' : 'bg-cl-bg text-cl-text-2 hover:text-cl-text') + '" data-qtab="' + t[0] + '">' + t[1] + ' ' + t[2] + '</button>';
            }).join('') + '</div>';
            if (!list.length) {
                h += '<p class="text-xs text-cl-text-3 py-2">该分类下暂无题目</p>';
            } else {
                h += '<div class="space-y-2">' + slice.map(function (q) {
                    var idx = all.indexOf(q);
                    var stars = '★'.repeat(q.mastery_stars || 0) + '☆'.repeat(Math.max(0, 5 - (q.mastery_stars || 0)));
                    return '<div class="rounded-clbtn bg-cl-bg px-3 py-2">'
                        + '<div class="flex items-start gap-2">'
                        + '<span class="cl-badge shrink-0 ' + (isWrongQ(q) ? 'bg-cl-danger-soft text-cl-danger' : 'bg-cl-secondary-soft text-cl-secondary') + '">' + (q.last_result === '正确' ? '上次正确' : '上次错误') + '</span>'
                        + '<p class="text-[13px] text-cl-text flex-1 min-w-0 break-words whitespace-pre-wrap">' + esc(truncate(q.content, 120)) + '</p></div>'
                        + '<div class="flex items-center justify-between gap-2 mt-1 flex-wrap">'
                        + '<p class="text-[11px] text-cl-text-3">' + esc(q.type || '未分类') + ' · 练习 ' + esc(String(q.practice_count)) + ' 次 · 答对 ' + esc(String(q.correct_count)) + ' 次 · 熟练度 ' + stars
                        + (q.is_favorite ? ' · 已收藏' : '') + ' · ' + esc(relTime(q.last_practice_time)) + '</p>'
                        + '<div class="flex items-center gap-2 shrink-0">'
                        + '<button class="cl-btn-ghost !h-7 text-[11px]" data-qview="' + idx + '">' + icon('search', 'w-3.5 h-3.5') + ' 查看</button>'
                        + '<button class="cl-btn-ghost !h-7 text-[11px]" data-qprac="' + idx + '">' + icon('dumbbell', 'w-3.5 h-3.5') + ' 练习</button>'
                        // P5：编辑/删除仅错题开放（用户裁定，非错题不动流水）
                        + (isWrongQ(q) ? '<button class="cl-btn-ghost !h-7 text-[11px]" data-qedit="' + idx + '">编辑</button>'
                            + '<button class="cl-btn-ghost !h-7 text-[11px] text-cl-danger" data-qdel="' + idx + '">删除</button>' : '')
                        + '</div></div></div>';
                }).join('') + '</div>';
            }
            if (pages > 1) h += '<div class="flex items-center justify-center gap-3 mt-3">'
                + '<button class="cl-btn-ghost !h-7 text-xs" data-qpage="prev"' + (qView.page <= 1 ? ' disabled' : '') + '>' + icon('chevron-left', 'w-3.5 h-3.5') + ' 上一页</button>'
                + '<span class="text-xs text-cl-text-3">第 ' + qView.page + ' / ' + pages + ' 页（共 ' + list.length + ' 题）</span>'
                + '<button class="cl-btn-ghost !h-7 text-xs" data-qpage="next"' + (qView.page >= pages ? ' disabled' : '') + '>下一页 ' + icon('chevron-right', 'w-3.5 h-3.5') + '</button></div>';
            box.innerHTML = h;
            box.querySelectorAll('[data-qtab]').forEach(function (b) {
                b.addEventListener('click', function () { qView.tab = b.getAttribute('data-qtab'); qView.page = 1; renderQuestions(); });
            });
            box.querySelectorAll('[data-qview]').forEach(function (b) {
                b.addEventListener('click', function () { openQuestionModal(all[Number(b.getAttribute('data-qview'))].content); });
            });
            box.querySelectorAll('[data-qprac]').forEach(function (b) {
                b.addEventListener('click', function () {
                    var p = b;
                    p.disabled = true;
                    fetchQuestionDetail(all[Number(p.getAttribute('data-qprac'))].content).then(function (q) {
                        p.disabled = false;
                        startSinglePractice(q);
                    }).catch(function (e) { p.disabled = false; hint('题目详情加载失败：' + e.message, true); });
                });
            });
            // —— P5 错题行：编辑（题干/选项/答案/解析）与删除（确认制） ——
            box.querySelectorAll('[data-qedit]').forEach(function (b) {
                b.addEventListener('click', function () {
                    b.disabled = true;
                    fetchQuestionDetail(all[Number(b.getAttribute('data-qedit'))].content).then(function (q) {
                        b.disabled = false;
                        if (!q.error || !q.error.error_id) { hint('该题已不在错题本，无法编辑', true); return; }
                        openErrorEditModal(q);
                    }).catch(function (e) { b.disabled = false; hint('题目详情加载失败：' + e.message, true); });
                });
            });
            box.querySelectorAll('[data-qdel]').forEach(function (b) {
                b.addEventListener('click', function () {
                    b.disabled = true;
                    fetchQuestionDetail(all[Number(b.getAttribute('data-qdel'))].content).then(function (q) {
                        b.disabled = false;
                        if (!q.error || !q.error.error_id) { hint('该题已不在错题本', true); return; }
                        // 删除确认制（用户裁定）：purge 整题——错题行+熟练度历史+本知识点下流水/收藏
                        if (!window.confirm('删除这道错题？将同时清除它在本知识点下的练习记录与收藏，不可恢复。')) return;
                        sendJSON('DELETE', '/api/kb/errors/' + q.error.error_id).then(function (d) {
                            if (d && d.deleted) { hint('已删除该错题及其练习留痕'); loadLinkedQuestions(); }
                            else hint('删除失败：错题可能已被移除', true);
                        }).catch(function (e) { hint('删除失败：' + e.message, true); });
                    }).catch(function (e) { b.disabled = false; hint('题目详情加载失败：' + e.message, true); });
                });
            });
            box.querySelectorAll('[data-qpage]').forEach(function (b) {
                b.addEventListener('click', function () {
                    qView.page += b.getAttribute('data-qpage') === 'next' ? 1 : -1;
                    renderQuestions();
                    box.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                });
            });
        }
        // —— 题目详情：拉取 + 模态展示（题干/选项/全部作答流水/错题信息） ——
        function fetchQuestionDetail(content) {
            return getJSON('/api/knowledge/points/' + encodeURIComponent(pid) + '/question-detail?content=' + encodeURIComponent(content))
                .then(function (d) {
                    if (!d || d.success !== true) throw new Error((d && d.error) || '详情加载失败');
                    return d.question;
                });
        }
        function closeQModal() { var m = main.querySelector('[data-role="q-modal"]'); if (m) m.remove(); }
        function openQuestionModal(content) {
            closeQModal();
            var ov = document.createElement('div');
            ov.setAttribute('data-role', 'q-modal');
            ov.className = 'fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4';
            ov.innerHTML = '<div class="cl-card p-6 w-full max-w-2xl max-h-[85vh] overflow-y-auto"><p class="text-sm text-cl-text-2 py-8 text-center">正在加载题目详情…</p></div>';
            ov.addEventListener('click', function (e) { if (e.target === ov) closeQModal(); });
            main.appendChild(ov);
            fetchQuestionDetail(content).then(function (q) {
                if (!guard(ov)) return;
                ov.firstElementChild.innerHTML = questionModalHtml(q);
                var pb = ov.querySelector('[data-role="qmodal-prac"]');
                if (pb) pb.addEventListener('click', function () { startSinglePractice(q); });
                var cb = ov.querySelector('[data-role="qmodal-close"]');
                if (cb) cb.addEventListener('click', closeQModal);
            }).catch(function (e) {
                if (guard(ov)) ov.firstElementChild.innerHTML = '<p class="text-sm text-cl-danger py-6">详情加载失败：' + esc(e.message) + '</p>';
            });
        }
        function questionModalHtml(q) {
            var letter = function (i) { return String.fromCharCode(65 + i); };
            var h = '<div class="flex items-center justify-between mb-3">'
                + '<div class="cl-section-title">' + icon('target', 'w-4 h-4 text-cl-primary') + ' 题目详情</div>'
                + '<button class="text-cl-text-3 hover:text-cl-text" data-role="qmodal-close" aria-label="关闭">' + icon('x', 'w-4 h-4') + '</button></div>';
            h += '<div class="flex items-center gap-2 mb-2 flex-wrap"><span class="cl-badge bg-cl-primary-soft text-cl-primary">' + esc(PRAC_TYPE_NAME[q.type] || _qtypeCN(q.type)) + '</span>'
                + '<span class="text-[11px] text-cl-text-3">练习 ' + esc(String(q.practice_count)) + ' 次 · 答对 ' + esc(String(q.correct_count)) + ' 次' + (q.is_favorite ? ' · 已收藏' : '') + '</span></div>';
            h += '<p class="text-sm font-medium text-cl-text break-words whitespace-pre-wrap">' + esc(q.content) + '</p>';
            if (q.options && q.options.length) {
                h += '<div class="mt-3 space-y-1">' + q.options.map(function (o, i) {
                    // P2 评审修复 m-4：与 optionsHtml 同口径——字母前缀 || 选项文本兼容存量数据
                    var ca = String((q.error && q.error.correct_answer) || '').trim();
                    var right = ca !== '' && (ca.toUpperCase().indexOf(letter(i)) === 0 || String(o).trim() === ca);
                    return '<p class="text-[13px] text-cl-text-2' + (right ? ' font-semibold text-cl-secondary' : '') + '"><strong>' + letter(i) + '.</strong> ' + esc(o) + (right ? ' ✓' : '') + '</p>';
                }).join('') + '</div>';
            }
            if (q.error) {
                h += '<div class="rounded-clbtn bg-cl-bg px-3 py-2 mt-4">'
                    + '<p class="text-xs font-semibold text-cl-danger mb-1">错题信息</p>'
                    + '<p class="text-xs text-cl-text-2">正确答案：' + esc(q.error.correct_answer || '未录入') + ' · 当前熟练度：' + esc(String(q.error.current_proficiency == null ? '-' : q.error.current_proficiency)) + '</p>'
                    + (q.error.explanation ? '<p class="text-xs text-cl-text-2 mt-1">解析：' + esc(q.error.explanation) + '</p>' : '') + '</div>';
            }
            h += '<div class="mt-4 pt-4 border-t border-cl-border"><p class="text-xs font-semibold text-cl-text-2 mb-2">全部作答记录（' + q.records.length + ' 次）</p>'
                + '<div class="space-y-1 max-h-56 overflow-y-auto">' + q.records.map(function (r) {
                    return '<div class="flex items-center gap-2 text-xs"><span class="shrink-0 ' + (r.is_correct ? 'text-cl-secondary' : 'text-cl-danger') + '">' + (r.is_correct ? '✓ 正确' : '✗ 错误') + '</span>'
                        + '<span class="text-cl-text-2 flex-1 min-w-0 break-words">答：' + esc(truncate(r.user_answer || '未答', 60)) + '</span>'
                        + '<span class="text-cl-text-3 shrink-0">' + esc(relTime(r.time)) + '</span></div>';
                }).join('') + '</div></div>';
            h += '<div class="flex items-center justify-end gap-3 mt-4 pt-4 border-t border-cl-border">'
                + '<button class="cl-btn-primary !h-9 text-xs" data-role="qmodal-prac">' + icon('dumbbell', 'w-4 h-4') + ' 练习此题</button></div>';
            return h;
        }
        function _qtypeCN(t) { return { single: '选择题', judge: '判断题', fill: '填空题', short: '简答题' }[t] || '未分类'; }
        // —— 单题练习：复用结构化答题/判分/落库通道（prac 状态机 1 题版） ——
        function startSinglePractice(q) {
            closeQModal(); // P2 评审修复 m-2：早退也先关模态，否则 hint 被遮罩盖住
            if (!q.reference_answer) { hint('该题暂无判分基准（既无错题答案也无历史正确作答），可先生成新一轮练习', true); return; }
            // P2 评审修复 M-1：批量生成中/答题中覆盖前确认（生成已耗积分，不静默丢弃）
            var pp = main.querySelector('[data-role="practice-panel"]');
            var batchActive = prac.qs.length > 1 && pp && !pp.classList.contains('hidden')
                && prac.ans.some(function (a) { return a !== null; });
            if (prac.generating || batchActive) {
                if (!window.confirm('当前有进行中的批量练习（含已扣积分的生成请求），开始单题练习将丢弃其进度。继续？')) return;
                prac.gen++; prac.generating = false; // 作废在途生成回调
            }
            main.querySelector('[data-role="assess-panel"]').classList.add('hidden');
            prac.qs = [{ question: q.content, type: q.type, options: q.options || [], correct_answer: q.reference_answer, explanation: q.explanation || '', difficulty: '中等' }];
            prac.ans = [null]; prac.idx = 0; prac.title = '单题练习';
            hint('');
            renderPracticeQuestion();
            var p = main.querySelector('[data-role="practice-panel"]');
            if (p) p.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }

        function hint(msg, isErr) {
            var el = main.querySelector('[data-role="act-hint"]');
            if (el) el.innerHTML = isErr ? '<span class="text-cl-danger">' + esc(msg) + '</span>' : esc(msg);
        }
        function setBusy(btn, text) {
            btn.disabled = true; btn.dataset.origHtml = btn.innerHTML;
            btn.innerHTML = esc(text) + '…'; btn.classList.add('opacity-60', 'cursor-not-allowed');
        }
        function unset(btn) {
            btn.disabled = false;
            if (btn.dataset.origHtml) btn.innerHTML = btn.dataset.origHtml;
            btn.classList.remove('opacity-60', 'cursor-not-allowed');
        }
        // u10 CodeReview m-4：三个动作共用面板/互相冲突，请求期间锁定其余按钮，链尾统一解锁
        function lockActs(btn) { main.querySelectorAll('[data-act]').forEach(function (x) { if (x !== btn) x.disabled = true; }); }
        function unlockActs(btn) {
            unset(btn);
            main.querySelectorAll('[data-act]').forEach(function (x) { x.disabled = false; });
        }
        function panel(role) { var p = main.querySelector('[data-role="' + role + '"]'); p.classList.remove('hidden'); return p; }
        function guard(p) { return document.contains(p); } // 片段已切换则丢弃异步回写（同批 6 M-3 口径）

        // —— 动作 1：熟练度评估（页内轮播答题 → 提交 → 结果 + 刷新掌握度） ——
        var assess = { qs: [], ans: [], idx: 0 };
        function startAssess(btn) {
            setBusy(btn, '生成题目中'); lockActs(btn);
            Promise.resolve(window.bridge.generateAssessmentQuestions(pid)).then(function (s) {
                unlockActs(btn);
                if (!guard(main)) return;
                var r = parseBridge(s);
                if (r.success !== true || !r.questions || !r.questions.length) {
                    hint(r.credits_insufficient ? '积分不足：' + (r.error || '请先充值') : (r.error || '题目生成失败'), true);
                    return;
                }
                hint('');
                assess.qs = r.questions; assess.ans = new Array(r.questions.length).fill(null); assess.idx = 0;
                renderQuestion();
            }).catch(function (e) { unlockActs(btn); hint('评估题目生成失败：' + e.message, true); });
        }
        function renderQuestion() {
            var p = panel('assess-panel');
            var q = assess.qs[assess.idx];
            var total = assess.qs.length;
            var pct = Math.round(((assess.idx + 1) / total) * 100);
            var h = '<div class="flex items-center justify-between mb-3">';
            h += '<div class="cl-section-title">' + icon('sparkles', 'w-4 h-4 text-cl-primary') + ' 熟练度评估</div>';
            h += '<button class="text-cl-text-3 hover:text-cl-text" data-role="assess-close" aria-label="关闭">' + icon('x', 'w-4 h-4') + '</button></div>';
            h += '<div class="flex items-center gap-3 mb-4"><div class="flex-1 cl-progress"><div class="cl-progress-bar" style="width:' + pct + '%"></div></div>'
                + '<span class="text-xs text-cl-text-3 shrink-0">' + (assess.idx + 1) + '/' + total + '</span></div>';
            h += '<div class="flex items-center gap-2 mb-2"><span class="cl-badge bg-cl-primary-soft text-cl-primary">题目 ' + (assess.idx + 1) + '</span>'
                + '<span class="text-xs text-cl-text-3">难度: ' + esc(q.difficulty || '中等') + '</span></div>';
            h += mdqHtml(q.question, 'text-sm font-medium text-cl-text mb-3 break-words');
            h += '<div class="space-y-2">';
            (q.options || []).forEach(function (opt, i) {
                var letter = String.fromCharCode(65 + i);
                var checked = assess.ans[assess.idx] === letter ? ' checked' : '';
                h += '<label class="flex items-center gap-3 rounded-clbtn border border-cl-border px-3 py-2 cursor-pointer hover:bg-cl-bg">'
                    + '<input type="radio" name="kp-assess" value="' + letter + '"' + checked + '>'
                    + '<span class="text-[13px] text-cl-text-2"><strong>' + letter + '.</strong> ' + mdqHtml(opt, '', true) + '</span></label>';
            });
            h += '</div>';
            h += '<div class="flex items-center justify-between mt-5">';
            h += '<button class="cl-btn-ghost !h-8 text-xs" data-role="assess-prev"' + (assess.idx === 0 ? ' disabled' : '') + '>上一题</button>';
            h += '<button class="cl-btn-primary !h-8 text-xs" data-role="assess-next">' + (assess.idx === total - 1 ? '提交评估' : '下一题') + '</button></div>';
            p.innerHTML = h;
            hydrateMdSlots(p); // 题干/选项公式与 MD 统一渲染（与错题行同管线）
            p.querySelector('[data-role="assess-close"]').addEventListener('click', function () { p.classList.add('hidden'); p.innerHTML = ''; });
            var prev = p.querySelector('[data-role="assess-prev"]');
            if (prev && assess.idx > 0) prev.addEventListener('click', function () { pickAns(p); assess.idx--; renderQuestion(); });
            p.querySelector('[data-role="assess-next"]').addEventListener('click', function () {
                pickAns(p);
                if (assess.ans[assess.idx] == null) { hint('请先选择一个答案', true); return; }
                hint('');
                if (assess.idx < assess.qs.length - 1) { assess.idx++; renderQuestion(); } else submitAssess(p);
            });
        }
        function pickAns(p) {
            var r = p.querySelector('input[name="kp-assess"]:checked');
            if (r) assess.ans[assess.idx] = r.value;
        }
        function submitAssess(p) {
            p.innerHTML = '<p class="text-sm text-cl-text-2 py-6 text-center">正在评估答题情况…</p>';
            Promise.resolve(window.bridge.submitMasteryAssessment(pid, JSON.stringify(assess.qs), JSON.stringify(assess.ans))).then(function (s) {
                if (!guard(p)) return;
                var r = parseBridge(s);
                if (r.success !== true) { p.innerHTML = '<p class="text-sm text-cl-danger py-4">评估提交失败：' + esc(r.error || '未知错误') + '</p>'; return; }
                var score = Number(r.mastery_score) || 0;
                var level = score >= 90 ? '精通' : score >= 70 ? '熟练' : score >= 50 ? '一般' : '待提高';
                var h = '<div class="text-center py-2">';
                h += '<div class="inline-flex items-center justify-center w-20 h-20 rounded-full bg-cl-primary-soft mb-3"><span class="text-2xl font-bold text-cl-primary">' + score + '</span></div>';
                h += '<p class="text-base font-semibold text-cl-text">熟练度：' + level + '</p>';
                h += '<p class="text-xs text-cl-text-2 mt-1">答对 ' + esc(String(r.correct_count)) + '/' + esc(String(r.total_count)) + ' 题</p></div>';
                h += '<div class="mt-4 pt-4 border-t border-cl-border space-y-3">';
                (r.detailed_results || []).forEach(function (d) {
                    // 原题选项随结果展示（2026-10-08 用户要求）：本地 assess.qs 按题序回取原题数据
                    var oq = assess.qs[d.question_index] || {};
                    h += '<div class="rounded-clbtn bg-cl-bg px-3 py-2">'
                        + '<div class="flex items-start gap-2">' + (d.is_correct ? icon('check', 'w-4 h-4 text-cl-secondary shrink-0') : icon('x', 'w-4 h-4 text-cl-danger shrink-0'))
                        + mdqHtml(d.question, 'text-[13px] text-cl-text flex-1 break-words max-h-32 overflow-y-auto') + '</div>'
                        + optionsHtml(oq, true, d.user_answer)
                        + '<p class="text-xs text-cl-text-3 mt-1">你的答案：' + mdqHtml(d.user_answer || '未选', '', true) + '　正确答案：' + mdqHtml(d.correct_answer, '', true) + '</p>'
                        + (d.explanation ? '<div class="mt-1"><span class="text-xs text-cl-text-3">解析：</span>' + mdqHtml(d.explanation, 'text-xs text-cl-text-3 break-words') + '</div>' : '') + '</div>';
                });
                h += '</div>';
                p.innerHTML = h;
                hydrateMdSlots(p); // 评估结果：原题/答/解析公式渲染
                // 头部掌握度同步刷新（免重拉详情）
                if (state.det) {
                    state.det.mastery_score = score;
                    var ms = main.querySelector('[data-role="mastery-slot"]');
                    var ps = main.querySelector('[data-role="progress-slot"]');
                    if (ms) ms.innerHTML = masteryBadge(score);
                    if (ps) ps.innerHTML = progressBar(score);
                }
                mountMemoryWidgets(main, 'kp', pid); // 评审 c3 Major-1：评估复习落库后重挂面板（新曲线/星级/清 manual 标记）
                loadLinkedQuestions(); // P1 评审修复：评估产生新流水/错题后关联题目列表同步刷新
                hint('评估完成，掌握度已更新');
            }).catch(function (e) { if (guard(p)) p.innerHTML = '<p class="text-sm text-cl-danger py-4">评估提交异常：' + esc(e.message) + '</p>'; });
        }

        // —— 动作 2/3：基于笔记练习、举一反三（2026-10-02 改造：结构化多题型答题模板，自由文本版下线） ——
        function showPracticeLoading(title) {
            var p = panel('practice-panel');
            main.querySelector('[data-role="assess-panel"]').classList.add('hidden');
            p.innerHTML = '<div class="cl-section-title mb-2">' + icon('book-open', 'w-4 h-4 text-cl-primary') + ' ' + esc(title) + '</div>'
                + '<p class="text-sm text-cl-text-2">题目生成中，可能需要几十秒，请稍候…</p>';
            return p;
        }
        var PRAC_TYPE_NAME = { single: '选择题', judge: '判断题', fill: '填空题', short: '简答题' };
        var prac = { qs: [], ans: [], idx: 0, title: '', gen: 0, generating: false }; // P2 评审修复 M-1：gen 令牌作废迟到的批量生成回调
        // u10 CodeReview m-2 口径延续：空态（灰）/接口错误（红，不吞）分开呈现
        function practiceMsg(r) {
            if (r.no_notes) return { text: '该知识点暂无关联笔记，无法生成练习。可先到「学」页学习并提取知识点关联笔记。', empty: true };
            if (r.no_errors) return { text: '该知识点暂无错题记录，无需举一反三。可先做一轮熟练度评估或从笔记练习。', empty: true };
            if (r.credits_insufficient) return { text: '积分不足：' + (r.error || '请先充值'), empty: false };
            return { text: r.error || '题目生成失败，请稍后重试', empty: false };
        }
        function startPointPractice(btn, source, title) {
            setBusy(btn, '生成题目中'); lockActs(btn);
            var p = showPracticeLoading(title);
            prac.title = title;
            var myGen = ++prac.gen; prac.generating = true; // P2 评审修复 M-1
            Promise.resolve(window.bridge.generatePointPractice(pid, source)).then(function (s) {
                if (prac.gen !== myGen) return; // 已被单题练习等后继操作作废
                prac.generating = false;
                if (!guard(p)) return;
                var r = parseBridge(s);
                if (r.success !== true || !r.questions || !r.questions.length) {
                    var m = practiceMsg(r);
                    p.innerHTML = '<div class="cl-section-title mb-2">' + icon('book-open', 'w-4 h-4 text-cl-primary') + ' ' + esc(title) + '</div>'
                        + '<p class="text-sm ' + (m.empty ? 'text-cl-text-2' : 'text-cl-danger') + ' py-2">' + esc(m.text) + '</p>';
                    if (!m.empty) hint(title + '生成失败', true);
                    return;
                }
                prac.qs = r.questions; prac.ans = new Array(r.questions.length).fill(null); prac.idx = 0;
                renderPracticeQuestion();
            }).catch(function (e) {
                if (prac.gen !== myGen) return;
                prac.generating = false;
                if (!guard(p)) return;
                p.innerHTML = '<p class="text-sm text-cl-danger py-2">' + esc(title + '生成失败：' + (e.message || '未知错误')) + '</p>';
            }).then(function () { unlockActs(btn); });
        }
        function pickPracAns(p) {
            var r = p.querySelector('input[name="kp-prac"]:checked');
            if (r) { prac.ans[prac.idx] = r.value; return; }
            var inp = p.querySelector('[data-role="prac-text"]');
            if (inp) { var v = inp.value.trim(); prac.ans[prac.idx] = v ? v : null; }
        }
        function renderPracticeQuestion() {
            var p = panel('practice-panel');
            var q = prac.qs[prac.idx];
            var total = prac.qs.length;
            var pct = Math.round(((prac.idx + 1) / total) * 100);
            var h = '<div class="flex items-center justify-between mb-3">';
            h += '<div class="cl-section-title">' + icon('book-open', 'w-4 h-4 text-cl-primary') + ' ' + esc(prac.title) + '</div>';
            h += '<button class="text-cl-text-3 hover:text-cl-text" data-role="prac-close" aria-label="关闭">' + icon('x', 'w-4 h-4') + '</button></div>';
            h += '<div class="flex items-center gap-3 mb-4"><div class="flex-1 cl-progress"><div class="cl-progress-bar" style="width:' + pct + '%"></div></div>'
                + '<span class="text-xs text-cl-text-3 shrink-0">' + (prac.idx + 1) + '/' + total + '</span></div>';
            h += '<div class="flex items-center gap-2 mb-2">'
                + '<span class="cl-badge bg-cl-primary-soft text-cl-primary">题目 ' + (prac.idx + 1) + '</span>'
                + '<span class="cl-badge bg-cl-secondary-soft text-cl-secondary">' + esc(PRAC_TYPE_NAME[q.type] || '选择题') + '</span>'
                + '<span class="text-xs text-cl-text-3">难度: ' + esc(q.difficulty || '中等') + '</span></div>';
            h += mdqHtml(q.question, 'text-sm font-medium text-cl-text mb-3 break-words');
            if (q.type === 'single' || q.type === 'judge') {
                h += '<div class="space-y-2">';
                if (q.type === 'judge') {
                    ['正确', '错误'].forEach(function (v) {
                        h += '<label class="flex items-center gap-3 rounded-clbtn border border-cl-border px-3 py-2 cursor-pointer hover:bg-cl-bg">'
                            + '<input type="radio" name="kp-prac" value="' + esc(v) + '"' + (prac.ans[prac.idx] === v ? ' checked' : '') + '>'
                            + '<span class="text-[13px] text-cl-text-2">' + esc(v) + '</span></label>';
                    });
                } else {
                    (q.options || []).forEach(function (opt, i) {
                        var letter = String.fromCharCode(65 + i);
                        h += '<label class="flex items-center gap-3 rounded-clbtn border border-cl-border px-3 py-2 cursor-pointer hover:bg-cl-bg">'
                            + '<input type="radio" name="kp-prac" value="' + letter + '"' + (prac.ans[prac.idx] === letter ? ' checked' : '') + '>'
                            + '<span class="text-[13px] text-cl-text-2"><strong>' + letter + '.</strong> ' + mdqHtml(opt, '', true) + '</span></label>';
                    });
                }
                h += '</div>';
            } else if (q.type === 'fill') {
                h += '<input type="text" data-role="prac-text" maxlength="200" placeholder="填写空格处的答案"'
                    + ' class="w-full rounded-clbtn border border-cl-border px-3 py-2 text-sm text-cl-text focus:outline-none focus:border-cl-primary" value="' + esc(prac.ans[prac.idx] || '') + '">';
            } else {
                h += '<textarea data-role="prac-text" rows="5" maxlength="2000" placeholder="写下你的答案，提交后由 AI 对照参考答案判分"'
                    + ' class="w-full rounded-clbtn border border-cl-border px-3 py-2 text-sm text-cl-text focus:outline-none focus:border-cl-primary">' + esc(prac.ans[prac.idx] || '') + '</textarea>';
            }
            h += '<div class="flex items-center justify-between mt-5">';
            h += '<button class="cl-btn-ghost !h-8 text-xs" data-role="prac-prev"' + (prac.idx === 0 ? ' disabled' : '') + '>上一题</button>';
            h += '<button class="cl-btn-primary !h-8 text-xs" data-role="prac-next">' + (prac.idx === total - 1 ? '提交作答' : '下一题') + '</button></div>';
            p.innerHTML = h;
            hydrateMdSlots(p); // 题干/选项公式与 MD 统一渲染
            p.querySelector('[data-role="prac-close"]').addEventListener('click', function () { p.classList.add('hidden'); p.innerHTML = ''; });
            var prev = p.querySelector('[data-role="prac-prev"]');
            if (prev && prac.idx > 0) prev.addEventListener('click', function () { pickPracAns(p); prac.idx--; renderPracticeQuestion(); });
            p.querySelector('[data-role="prac-next"]').addEventListener('click', function () {
                pickPracAns(p);
                if (prac.ans[prac.idx] == null) { hint(q.type === 'short' ? '请简写作答后继续（AI 判分需要答案）' : '请先作答本题', true); return; }
                hint('');
                if (prac.idx < prac.qs.length - 1) { prac.idx++; renderPracticeQuestion(); } else submitPractice(p);
            });
        }
        function submitPractice(p) {
            p.innerHTML = '<p class="text-sm text-cl-text-2 py-6 text-center">正在判分…（含简答题时需 AI 判分，稍候）</p>';
            Promise.resolve(window.bridge.submitPointPractice(pid, prac.qs, prac.ans)).then(function (s) {
                if (!guard(p)) return;
                var r = parseBridge(s);
                if (r.success !== true) {
                    p.innerHTML = '<p class="text-sm text-cl-danger py-4">提交判分失败：'
                        + esc((r.credits_insufficient ? '积分不足：' + (r.error || '请先充值') : (r.error || '未知错误'))) + '</p>';
                    return;
                }
                var score = Number(r.mastery_score) || 0;
                var level = score >= 90 ? '精通' : score >= 70 ? '熟练' : score >= 50 ? '一般' : '待提高';
                var wrong = (r.detailed_results || []).filter(function (d) { return !d.is_correct; }).length;
                var h = '<div class="flex items-center justify-between mb-3">'
                    + '<div class="cl-section-title">' + icon('book-open', 'w-4 h-4 text-cl-primary') + ' ' + esc(prac.title) + ' · 判分结果</div>'
                    + '<button class="text-cl-text-3 hover:text-cl-text" data-role="prac-close" aria-label="关闭">' + icon('x', 'w-4 h-4') + '</button></div>';
                h += '<div class="text-center py-2">';
                h += '<div class="inline-flex items-center justify-center w-20 h-20 rounded-full bg-cl-primary-soft mb-3"><span class="text-2xl font-bold text-cl-primary">' + score + '</span></div>';
                h += '<p class="text-base font-semibold text-cl-text">熟练度：' + level + '</p>';
                h += '<p class="text-xs text-cl-text-2 mt-1">答对 ' + esc(String(r.correct_count)) + '/' + esc(String(r.total_count)) + ' 题'
                    + (wrong ? '，错题已入错题本' : '') + '</p></div>';
                h += '<div class="mt-4 pt-4 border-t border-cl-border space-y-3">';
                (r.detailed_results || []).forEach(function (d) {
                    // 原题选项随结果展示（与评估同口径）：填空/简答无 options，optionsHtml 自然返回空串
                    var oq = prac.qs[d.question_index] || {};
                    h += '<div class="rounded-clbtn bg-cl-bg px-3 py-2">'
                        + '<div class="flex items-start gap-2">' + (d.is_correct ? icon('check', 'w-4 h-4 text-cl-secondary shrink-0') : icon('x', 'w-4 h-4 text-cl-danger shrink-0'))
                        + mdqHtml(d.question, 'text-[13px] text-cl-text flex-1 break-words max-h-32 overflow-y-auto') + '</div>'
                        + optionsHtml(oq, true, d.user_answer)
                        + '<p class="text-xs text-cl-text-3 mt-1">你的答案：' + mdqHtml(d.user_answer || '未答', '', true) + '　正确答案：' + mdqHtml(d.correct_answer, '', true) + '</p>'
                        + (d.comment ? '<div class="mt-1"><span class="text-xs text-cl-text-3">AI 点评：</span>' + mdqHtml(d.comment, 'text-xs text-cl-text-3 break-words') + '</div>' : '')
                        + (d.explanation ? '<div class="mt-1"><span class="text-xs text-cl-text-3">解析：</span>' + mdqHtml(d.explanation, 'text-xs text-cl-text-3 break-words') + '</div>' : '') + '</div>';
                });
                h += '</div>';
                p.innerHTML = h;
                hydrateMdSlots(p); // 判分结果：原题/答/点评/解析公式渲染
                p.querySelector('[data-role="prac-close"]').addEventListener('click', function () { p.classList.add('hidden'); p.innerHTML = ''; });
                // 头部掌握度同步刷新（与评估同口径；错题数/最近练习在再次进入本页时刷新）
                if (state.det) {
                    state.det.mastery_score = score;
                    var ms = main.querySelector('[data-role="mastery-slot"]');
                    var ps = main.querySelector('[data-role="progress-slot"]');
                    if (ms) ms.innerHTML = masteryBadge(score);
                    if (ps) ps.innerHTML = progressBar(score);
                }
                mountMemoryWidgets(main, 'kp', pid); // 评审 c3 Major-1：练习复习落库后重挂面板
                loadLinkedQuestions(); // P1 评审修复：练习落库后关联题目计数/列表同步刷新
                hint(wrong ? '提交完成：错题已入错题本，稍后可举一反三' : '全部答对！掌握度已更新');
            }).catch(function (e) { if (guard(p)) p.innerHTML = '<p class="text-sm text-cl-danger py-4">提交异常：' + esc(e.message) + '</p>'; });
        }
        function startNotePractice(btn) { startPointPractice(btn, 'notes', '基于笔记练习'); }

        // —— P5 错题练习/举一反三（智能/手动模式弹窗）与错题编辑（2026-10-08） ——
        function closeChooser() {
            var m = main.querySelector('[data-role="ch-modal"]');
            if (m) { if (m._onEsc) document.removeEventListener('keydown', m._onEsc); m.remove(); }
        }
        // 错题清单：复用错题本端点（subject+知识点隔离）
        function getPointErrors() {
            var subject = (state.det && state.det.subject_name) || '';
            return getJSON('/api/kb/errors?subject=' + encodeURIComponent(subject) + '&kp_id=' + encodeURIComponent(pid));
        }
        // 同题干去重取熟练度最低代表行（与后端智能选题口径一致）
        function _profOf(e) { return e.current_proficiency == null ? 0 : e.current_proficiency; }
        function dedupErrors(list) {
            var best = {}, order = [];
            (list || []).forEach(function (e) {
                var k = e.question_content || '';
                if (!(k in best)) order.push(k);
                if (!(k in best) || _profOf(e) < _profOf(best[k])) best[k] = e;
            });
            return order.map(function (k) { return best[k]; }).sort(function (a, b) { return _profOf(a) - _profOf(b); });
        }
        // 组卷→答题统一包装：复用 prac 状态机/gen 令牌/空态口径，期间锁定其余动作按钮
        function runPracticeGen(title, runner) {
            var p = showPracticeLoading(title);
            prac.title = title;
            var myGen = ++prac.gen; prac.generating = true;
            main.querySelectorAll('[data-act]').forEach(function (x) { x.disabled = true; });
            var unlock = function () { main.querySelectorAll('[data-act]').forEach(function (x) { x.disabled = false; }); };
            Promise.resolve(runner()).then(function (r) {
                if (prac.gen !== myGen) return; // 已被后继操作作废（由后继链路负责解锁）
                prac.generating = false;
                if (!guard(p)) { unlock(); return; }
                if (!r || r.success !== true || !r.questions || !r.questions.length) {
                    var m = practiceMsg(r || { error: title + '启动失败' });
                    p.innerHTML = '<div class="cl-section-title mb-2">' + icon('book-open', 'w-4 h-4 text-cl-primary') + ' ' + esc(title) + '</div>'
                        + '<p class="text-sm ' + (m.empty ? 'text-cl-text-2' : 'text-cl-danger') + ' py-2">' + esc(m.text) + '</p>';
                    if (!m.empty) hint(title + '启动失败', true);
                    return;
                }
                prac.qs = r.questions; prac.ans = new Array(r.questions.length).fill(null); prac.idx = 0;
                renderPracticeQuestion();
            }).catch(function (e) {
                if (prac.gen !== myGen) return;
                prac.generating = false;
                if (guard(p)) p.innerHTML = '<p class="text-sm text-cl-danger py-2">' + esc(title + '启动失败：' + (e.message || '未知错误')) + '</p>';
            }).then(function () { if (prac.gen === myGen) unlock(); }); // CodeReview Minor-3：后继链路负责解锁时不得提前放开
        }
        // kind: 'error'=错题练习（零积分） 'analogy'=举一反三（LLM 耗积分）
        function openPracticeChooser(kind) {
            closeChooser();
            var isErr = kind === 'error';
            var counts = isErr ? [3, 5, 10] : [5, 10, 15];
            var countSel = counts[1];
            var tab = 'smart';
            var rows = [];
            var ov = document.createElement('div');
            ov.setAttribute('data-role', 'ch-modal');
            ov.className = 'fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4';
            ov.innerHTML = '<div class="cl-card p-6 w-full max-w-2xl max-h-[80vh] overflow-y-auto">'
                + '<div class="flex items-center justify-between mb-3"><div class="cl-section-title">'
                + icon(isErr ? 'dumbbell' : 'lightbulb', 'w-4 h-4 text-cl-primary') + ' ' + (isErr ? '错题练习' : '举一反三练习') + '</div>'
                + '<button class="text-cl-text-3 hover:text-cl-text" data-role="ch-close" aria-label="关闭">' + icon('x', 'w-4 h-4') + '</button></div>'
                + '<div class="flex items-center gap-2 mb-4">'
                + '<button class="cl-badge" data-chtab="smart">智能选题</button>'
                + '<button class="cl-badge" data-chtab="manual">手动勾题</button></div>'
                + '<div data-role="ch-body"><p class="text-xs text-cl-text-3 py-4">正在加载错题清单…</p></div></div>';
            ov.addEventListener('click', function (e) { if (e.target === ov) closeChooser(); });
            ov._onEsc = function (e) { if (e.key === 'Escape') closeChooser(); };
            document.addEventListener('keydown', ov._onEsc);
            main.appendChild(ov);
            var body = ov.querySelector('[data-role="ch-body"]');
            ov.querySelector('[data-role="ch-close"]').addEventListener('click', closeChooser);
            ov.querySelectorAll('[data-chtab]').forEach(function (b) {
                b.addEventListener('click', function () { tab = b.getAttribute('data-chtab'); render(); });
            });
            function render() {
                ov.querySelectorAll('[data-chtab]').forEach(function (b) {
                    var on = b.getAttribute('data-chtab') === tab;
                    b.className = 'cl-badge cursor-pointer transition-colors ' + (on ? 'bg-cl-primary-soft text-cl-primary' : 'bg-cl-bg text-cl-text-2 hover:text-cl-text');
                });
                if (!rows.length) {
                    body.innerHTML = '<p class="text-xs text-cl-text-3 py-4">该知识点还没有可练习的错题。先做一轮「熟练度评估」或「基于笔记练习」，答错的题会自动进入错题本。</p>';
                    return;
                }
                if (tab === 'smart') {
                    body.innerHTML = '<p class="text-xs text-cl-text-2 mb-3">按熟练度从低到高自动选最薄弱的错题'
                        + (isErr ? '（直接组卷答题，不消耗积分）' : '（AI 针对薄弱考点生成相似新题，会消耗积分）') + '。</p>'
                        + '<div class="flex items-center gap-2 mb-4 flex-wrap">练习题量：'
                        + counts.map(function (c) {
                            return '<button class="cl-badge cursor-pointer ' + (c === countSel ? 'bg-cl-primary-soft text-cl-primary' : 'bg-cl-bg text-cl-text-2 hover:text-cl-text') + '" data-chcnt="' + c + '">' + c + ' 题</button>';
                        }).join('') + '</div>'
                        + '<div class="flex justify-end"><button class="cl-btn-primary !h-9 text-xs" data-chstart>开始</button></div>';
                    body.querySelectorAll('[data-chcnt]').forEach(function (b) {
                        b.addEventListener('click', function () { countSel = Number(b.getAttribute('data-chcnt')); render(); });
                    });
                    body.querySelector('[data-chstart]').addEventListener('click', function () {
                        closeChooser();
                        if (isErr) {
                            runPracticeGen('错题练习 · 智能', function () {
                                return postJSON('/api/knowledge/points/' + encodeURIComponent(pid) + '/error-practice', { mode: 'smart', count: countSel });
                            });
                        } else {
                            runPracticeGen('举一反三练习', function () {
                                return window.bridge.generatePointPractice(pid, 'analogy', { count: countSel }).then(parseBridge);
                            });
                        }
                    });
                } else {
                    body.innerHTML = '<p class="text-xs text-cl-text-2 mb-3">勾选错题'
                        + (isErr ? '（只练所选，不消耗积分）' : '（AI 只针对所选考点出题，会消耗积分）') + '。同题干已去重，按熟练度升序。缺正确答案的行无法判分，不可勾。</p>'
                        + '<div class="space-y-2 max-h-72 overflow-y-auto mb-4">' + rows.map(function (r, i) {
                            var noAns = !String(r.correct_answer || '').trim();
                            return '<label class="flex items-start gap-2 rounded-clbtn border border-cl-border px-3 py-2 ' + (noAns ? 'opacity-50' : 'cursor-pointer hover:bg-cl-bg') + '">'
                                + '<input type="checkbox" data-chrow="' + i + '"' + (noAns ? ' disabled' : ' checked') + ' class="mt-0.5 shrink-0">'
                                + '<span class="flex-1 min-w-0"><span class="block text-[13px] text-cl-text break-words">' + esc(truncate(r.question_content, 90)) + '</span>'
                                + '<span class="block text-[11px] text-cl-text-3 mt-0.5">熟练度 ' + esc(String(_profOf(r))) + (noAns ? ' · 缺正确答案' : '') + '</span></span></label>';
                        }).join('') + '</div>'
                        + '<div class="flex justify-end"><button class="cl-btn-primary !h-9 text-xs" data-chstart></button></div>';
                    var startBtn = body.querySelector('[data-chstart]');
                    function syncStart() {
                        var n = body.querySelectorAll('[data-chrow]:checked').length;
                        startBtn.disabled = n === 0;
                        startBtn.textContent = isErr ? '练习所选 ' + n + ' 题' : '针对所选生成 ' + n + ' 题';
                    }
                    body.querySelectorAll('[data-chrow]').forEach(function (cb) { cb.addEventListener('change', syncStart); });
                    syncStart();
                    startBtn.addEventListener('click', function () {
                        var ids = [];
                        body.querySelectorAll('[data-chrow]:checked').forEach(function (cb) {
                            ids.push(rows[Number(cb.getAttribute('data-chrow'))].id);
                        });
                        closeChooser();
                        if (isErr) {
                            runPracticeGen('错题练习 · 手动', function () {
                                return postJSON('/api/knowledge/points/' + encodeURIComponent(pid) + '/error-practice', { mode: 'manual', error_ids: ids });
                            });
                        } else {
                            runPracticeGen('举一反三 · 针对所选', function () {
                                return window.bridge.generatePointPractice(pid, 'analogy', { count: Math.min(ids.length, 20), error_ids: ids }).then(parseBridge);
                            });
                        }
                    });
                }
            }
            getPointErrors().then(function (list) {
                if (!guard(ov)) return;
                rows = dedupErrors(list);
                render();
            }).catch(function (e) {
                if (guard(ov)) body.innerHTML = '<p class="text-xs text-cl-danger py-4">错题清单加载失败：' + esc(e.message) + '</p>';
            });
        }
        // —— 错题编辑弹层：题干/选项（同步流水）+ 正确答案/解析 ——
        function openErrorEditModal(q) {
            var old = main.querySelector('[data-role="qedit-modal"]'); if (old) old.remove();
            var isSingle = q.type === 'single';
            var opts = (q.options || []).slice(0, 4);
            var ov = document.createElement('div');
            ov.setAttribute('data-role', 'qedit-modal');
            ov.className = 'fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4';
            var inputCls = 'w-full rounded-clbtn border border-cl-border px-3 py-2 text-sm text-cl-text focus:outline-none focus:border-cl-primary';
            var h = '<div class="cl-card p-6 w-full max-w-xl max-h-[85vh] overflow-y-auto">'
                + '<div class="flex items-center justify-between mb-4"><div class="cl-section-title">' + icon('target', 'w-4 h-4 text-cl-primary') + ' 编辑错题</div>'
                + '<button class="text-cl-text-3 hover:text-cl-text" data-role="qe-close" aria-label="关闭">' + icon('x', 'w-4 h-4') + '</button></div>'
                + '<label class="block text-xs font-semibold text-cl-text-2 mb-1">题干（修正后本知识点下同题干的练习留痕一并更新）</label>'
                + '<textarea data-role="qe-content" rows="3" maxlength="1000" class="' + inputCls + ' mb-3">' + esc(q.content) + '</textarea>';
            if (isSingle) {
                h += '<label class="block text-xs font-semibold text-cl-text-2 mb-1">选项（A–D 四项均必填）</label><div class="space-y-2 mb-3">'
                    + [0, 1, 2, 3].map(function (i) {
                        return '<div class="flex items-center gap-2"><span class="text-xs text-cl-text-3 w-4 shrink-0">' + String.fromCharCode(65 + i) + '.</span>'
                            + '<input type="text" maxlength="200" data-qe-opt="' + i + '" class="flex-1 rounded-clbtn border border-cl-border px-3 py-2 text-sm text-cl-text focus:outline-none focus:border-cl-primary" value="' + esc(opts[i] || '') + '"></div>';
                    }).join('') + '</div>';
            }
            h += '<label class="block text-xs font-semibold text-cl-text-2 mb-1">正确答案' + (isSingle ? '（填 A/B/C/D，判分按首字母比较）' : '') + '</label>'
                + '<input type="text" data-role="qe-answer" maxlength="200" class="' + inputCls + ' mb-3" value="' + esc((q.error && q.error.correct_answer) || '') + '">'
                + '<label class="block text-xs font-semibold text-cl-text-2 mb-1">解析</label>'
                + '<textarea data-role="qe-expl" rows="2" maxlength="1000" class="' + inputCls + '">' + esc((q.error && q.error.explanation) || '') + '</textarea>'
                + '<p data-role="qe-hint" class="text-xs mt-2 min-h-4"></p>'
                + '<div class="flex items-center justify-end gap-3 mt-3 pt-3 border-t border-cl-border">'
                + '<button class="cl-btn-ghost !h-9 text-xs" data-role="qe-cancel">取消</button>'
                + '<button class="cl-btn-primary !h-9 text-xs" data-role="qe-save">保存</button></div></div>';
            ov.innerHTML = h;
            ov.addEventListener('click', function (e) { if (e.target === ov) closeEditModal(); });
            ov._onEsc = function (e) { if (e.key === 'Escape') closeEditModal(); };
            document.addEventListener('keydown', ov._onEsc);
            main.appendChild(ov);
            function closeEditModal() {
                if (ov._onEsc) document.removeEventListener('keydown', ov._onEsc);
                ov.remove();
            }
            function qeHint(msg) {
                // CodeReview Minor-4：异步回调时弹窗可能已被关闭（遮罩/Esc），脱离节点的提示不可见 → 降级为页面 toast
                var el = ov.isConnected ? ov.querySelector('[data-role="qe-hint"]') : null;
                if (!el) { hint(msg, true); return; }
                el.innerHTML = '<span class="text-cl-danger">' + esc(msg) + '</span>';
            }
            ov.querySelector('[data-role="qe-close"]').addEventListener('click', closeEditModal);
            ov.querySelector('[data-role="qe-cancel"]').addEventListener('click', closeEditModal);
            var saveBtn = ov.querySelector('[data-role="qe-save"]');
            saveBtn.addEventListener('click', function () {
                var content = ov.querySelector('[data-role="qe-content"]').value.trim();
                var answer = ov.querySelector('[data-role="qe-answer"]').value.trim();
                var expl = ov.querySelector('[data-role="qe-expl"]').value.trim();
                if (!content) { qeHint('题干不能为空'); return; }
                if (!answer) { qeHint('正确答案不能为空（后续练习判分基准）'); return; }
                var body = { content: content, correct_answer: answer, explanation: expl };
                if (isSingle) {
                    var list = [0, 1, 2, 3].map(function (i) {
                        return ov.querySelector('[data-qe-opt="' + i + '"]').value.trim();
                    });
                    if (list.some(function (v) { return !v; })) { qeHint('选择题四个选项须都填写'); return; }
                    body.options = list;
                }
                saveBtn.disabled = true;
                sendJSON('PUT', '/api/kb/errors/' + q.error.error_id, body).then(function (d) {
                    if (d && d.updated) {
                        closeEditModal();
                        hint('错题已更新，相关练习留痕已同步');
                        loadLinkedQuestions();
                        return;
                    }
                    saveBtn.disabled = false;
                    qeHint('保存失败：错题不存在或无权访问');
                }).catch(function (e) {
                    saveBtn.disabled = false;
                    qeHint('保存失败：' + e.message);
                });
            });
        }

        // —— 拉详情 ——
        getJSON('/api/knowledge/points/' + encodeURIComponent(pid) + '/detail').then(function (d) {
            // P032 双层契约：内层 success 显式校验（u9 CodeReview M-3 口径）
            if (!d || d.success !== true) throw new Error((d && d.error) || '知识点加载失败');
            renderAll(d.detail);
        }).catch(function (err) {
            main.innerHTML = '<div class="cl-card p-6"><p class="text-sm text-cl-danger">知识点加载失败：' + esc(err.message) + '</p>'
                + '<button class="cl-btn-ghost !h-9 text-xs mt-4" data-go="practice_overview">返回练习总览</button></div>';
            bindGoLinks(root);
        });
    }

    // ---------------- 工具导出（批6 起供其它页面复用，公共函数注册制：新页禁止再自写 tk/esc 等副本） ----------------
    global.pmUtil = { tk: tk, esc: esc, relTime: relTime, icon: icon, getJSON: getJSON, postJSON: postJSON, goMenu: goMenu, goPracticePoint: goPracticePoint, truncate: truncate, isUnrated: isUnrated, emptyBox: emptyBox };

    // ---------------- 启动分发 ----------------
    var BUILDERS = {
        practice_overview: bootPracticeOverview,
        memory_overview: bootMemoryOverview,
        practice_knowledge: bootPracticeKnowledge,
        practice_errors: bootPracticeErrors,
        memory_knowledge: bootMemoryKnowledge,
        memory_errors: bootMemoryErrors,
        knowledge_point: bootKnowledgePoint
    };
    function bootAll() {
        document.querySelectorAll('[data-pm-page]').forEach(function (root) {
            var name = root.getAttribute('data-pm-page');
            var fn = BUILDERS[name];
            if (fn) { try { fn(root); } catch (e) { console.error('[pm_pages]', name, e); } }
        });
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bootAll);
    } else {
        bootAll();
    }

    global.PmPages = { boot: bootAll, util: { esc: esc, relTime: relTime, getJSON: getJSON } };
})(window);
