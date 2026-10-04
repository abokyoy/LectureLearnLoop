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
    // 文本相等仅作兑底（防御存量异常数据）；无选项的存量旧题/判断题返回空串
    function optionsHtml(e, markCorrect) {
        if (!e || !e.options || !e.options.length) return '';
        var correctLetter = String(e.correct_answer || '').trim().slice(0, 1).toUpperCase();
        var correctText = String(e.correct_answer || '').trim();
        return '<div class="mt-3 space-y-1.5">' + e.options.map(function (o, idx) {
            var letter = String.fromCharCode(65 + idx);
            var isAns = markCorrect && (letter === correctLetter || (correctText !== '' && String(o).trim() === correctText));
            return '<div class="rounded-clbtn px-3 py-2 text-[13px] leading-relaxed ' + (isAns ? 'bg-cl-secondary-soft text-cl-secondary font-medium' : 'bg-cl-bg text-cl-text-2') + '">' + letter + '. ' + esc(o)
                + (isAns ? ' ' + icon('check', 'w-3.5 h-3.5 inline -mt-0.5') : '') + '</div>';
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
    function errorRow(e, opts) {
        var unrated = isUnrated(e.current_proficiency);
        var prof = unrated ? 0 : Math.max(0, Math.min(100, Number(e.current_proficiency) || 0));
        var reviewed = Number(e.review_status) === 1;
        var h = '<div class="cl-card p-5" data-eid="' + e.id + '">';
        h += '<div class="flex items-start justify-between gap-3">';
        h += '<button class="text-left flex-1 min-w-0 pm-q-toggle" data-toggle="' + e.id + '"><p class="text-sm font-medium text-cl-text">' + esc(truncate(e.question_content, 110)) + '</p></button>';
        h += '<span class="cl-badge shrink-0 ' + (reviewed ? 'bg-cl-secondary-soft text-cl-secondary' : 'bg-cl-primary-soft text-cl-primary') + '">' + (reviewed ? '已复习' : '待强化') + '</span>';
        h += '</div>';
        h += '<div class="flex items-center gap-3 mt-3">' + progressBar(e.current_proficiency)
            + '<span class="text-xs text-cl-text-3 whitespace-nowrap">' + (unrated ? '未评估' : prof + '%') + '</span></div>';
        h += '<p class="text-xs text-cl-text-3 mt-2">' + icon('clock', 'w-3.5 h-3.5 inline -mt-0.5') + ' 练习于 ' + esc(relTime(e.practice_time)) + '</p>';
        h += '<div class="hidden mt-3 pt-3 border-t border-cl-border space-y-2 text-xs" data-detail="' + e.id + '">';
        // 错题带选项时展开区直接列出（高亮正确项）；存量旧题未落库选项则不显示此块
        h += optionsHtml(e, true);
        h += '<p><span class="font-semibold text-cl-text-2">我的答案：</span><span class="' + (reviewed ? 'text-cl-text' : 'text-cl-danger') + '">' + esc(truncate(e.user_answer, 200) || '—') + '</span></p>';
        h += '<p><span class="font-semibold text-cl-text-2">正确答案：</span><span class="text-cl-secondary">' + esc(truncate(e.correct_answer, 200) || '—') + '</span></p>';
        if (e.explanation) h += '<p><span class="font-semibold text-cl-text-2">解析：</span><span class="text-cl-text-2">' + esc(truncate(e.explanation, 300)) + '</span></p>';
        h += '</div>';
        // 标记按钮放在折叠区外常显（批4 自测发现：藏在 hidden 详情内用户无法直接点击）
        if (opts && opts.reviewBtn && !reviewed) {
            h += '<div class="mt-3"><button class="cl-btn-ghost !h-8 !text-xs pm-review-btn" data-eid="' + e.id + '">' + icon('check-circle-2', 'w-4 h-4') + ' 标记已复习</button></div>';
        }
        h += '</div>';
        return h;
    }
    function bindErrorRows(root, opts) {
        root.querySelectorAll('.pm-q-toggle').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var d = root.querySelector('[data-detail="' + btn.getAttribute('data-toggle') + '"]');
                if (d) d.classList.toggle('hidden');
            });
        });
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
                                return '<div class="rounded-clbtn bg-cl-bg px-3 py-2"><p class="text-cl-text-2">' + esc(truncate(e.question_content, 90)) + '</p>'
                                    + '<p class="text-cl-text-3 mt-1">练习于 ' + esc(relTime(e.practice_time)) + ' · 熟练度 ' + (isUnrated(e.current_proficiency) ? '未评估' : (Number(e.current_proficiency) || 0) + '%') + '</p></div>';
                            }).join('');
                        }).catch(function (err) { box.innerHTML = '<p class="text-cl-danger">' + esc(err.message) + '</p>'; });
                    });
                });
            }).catch(function (err) {
                if (token !== latestTk(root)) return;
                main.innerHTML = '<p class="text-sm text-cl-danger py-6">知识点加载失败：' + esc(err.message) + '</p>';
            });
        });
    }

    // ---------------- 页2：基于错题练习 ----------------
    function bootPracticeErrors(root) {
        var search = root.querySelector('[data-role="search"]');
        var cache = { subject: '', rows: [] };
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
            main.innerHTML = '<div class="space-y-3">' + filtered.map(function (e) { return errorRow(e, { reviewBtn: false }); }).join('') + '</div>';
            bindErrorRows(main, { reviewBtn: false });
        }
        if (search) search.addEventListener('keydown', function (e) {
            if (e.key !== 'Enter') return;
            var main = root.querySelector('[data-role="main"]');
            if (cache.subject && main) render(main);
        });
        mountSubjects(root, function (subject, token) {
            var main = root.querySelector('[data-role="main"]');
            main.innerHTML = '<p class="text-sm text-cl-text-3 py-6">加载中…</p>';
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
            var h = toggleBar(pend.length);
            h += '<div class="flex items-center justify-between gap-3 mb-3 flex-wrap">';
            h += '<div class="flex items-center gap-2">' + (typeName ? '<span class="cl-badge bg-cl-primary-soft text-cl-primary">' + esc(typeName) + '</span>' : '')
                + '<span class="cl-badge ' + (round === 'done' ? 'bg-cl-secondary-soft text-cl-secondary' : 'bg-cl-bg text-cl-text-2') + '">' + (round === 'done' ? '巩固轮' : '待复习') + '</span>'
                + '<span class="text-xs text-cl-text-3">' + (unratedP ? '熟练度未评估' : '熟练度 ' + profKey(e) + '%') + ' · 练习于 ' + esc(relTime(e.practice_time)) + '</span></div>';
            h += '<span class="text-[13px] font-medium text-cl-text-2">第 ' + (qi + 1) + ' / ' + queue.length + ' 题</span></div>';
            // 卡片主体：点卡片翻转（正=题干+选项，背=答案+解析）
            h += '<div class="pm-flip-scene"><div class="pm-flip-card' + (flipped ? ' is-flipped' : '') + '" data-role="flip-card">';
            h += '<div class="pm-flip-face cl-card p-6 flex flex-col">';
            h += '<p class="text-[15px] leading-relaxed text-cl-text font-medium break-words">' + esc(e.question_content || '（题干缺失）') + '</p>';
            h += optionsHtml(e, false);
            h += '<p class="mt-auto pt-4 text-center text-xs text-cl-text-3">' + icon('refresh-cw', 'w-3.5 h-3.5 inline -mt-0.5') + ' 点击卡片看答案与解析</p>';
            h += '</div>';
            h += '<div class="pm-flip-face pm-flip-back cl-card p-6">';
            h += '<div class="cl-section-title mb-3">' + icon('lightbulb', 'w-4 h-4 text-cl-secondary') + ' 答案与解析</div>';
            h += '<p class="text-sm leading-relaxed"><span class="font-semibold text-cl-text-2">正确答案：</span><span class="text-cl-secondary font-medium">' + esc(truncate(e.correct_answer, 300) || '—') + '</span></p>';
            h += '<p class="text-sm leading-relaxed mt-2"><span class="font-semibold text-cl-text-2">我的答案：</span><span class="text-cl-danger">' + esc(truncate(e.user_answer, 300) || '—') + '</span></p>';
            h += optionsHtml(e, true);
            if (!e.options || !e.options.length) {
                h += '<p class="text-xs text-cl-text-3 mt-3 rounded-clbtn bg-cl-bg px-3 py-2">该题未保存选项（旧数据），仅对照答案与解析复习</p>';
            }
            if (e.explanation) h += '<p class="text-sm leading-relaxed mt-3"><span class="font-semibold text-cl-text-2">解析：</span><span class="text-cl-text-2">' + esc(truncate(e.explanation, 500)) + '</span></p>';
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

        function statCell(ic, cls, n, label) {
            return '<div class="flex items-center gap-3 rounded-clbtn bg-cl-bg px-3 py-2">'
                + '<span class="' + cls + '">' + icon(ic, 'w-4 h-4') + '</span>'
                + '<p class="text-[13px] text-cl-text-2"><strong class="text-cl-text">' + esc(String(n == null ? 0 : n)) + '</strong> ' + label + '</p></div>';
        }

        // —— 主体：详情 + 动作 + 面板 + 最近练习 ——
        function renderAll(det) {
            state.det = det;
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
            if (det.description) h += '<p class="text-sm text-cl-text-2 mt-4 leading-relaxed">' + esc(det.description) + '</p>';
            h += '<div class="grid grid-cols-1 sm:grid-cols-3 gap-3 mt-5 pt-5 border-t border-cl-border">';
            h += statCell('alert-circle', 'text-cl-danger', det.error_count, '道错题') + statCell('target', 'text-cl-secondary', det.favorite_count, '个收藏题') + statCell('file-text', 'text-cl-primary', det.notes_count, '篇关联笔记');
            h += '</div></div>';
            // 动作区：三个按钮全部页内闭环（旧脑图弹层依赖 AI 聊天窗全局函数，SPA 中不存在→断链，本页不再依赖）
            h += '<div class="cl-card p-4 flex items-center gap-3 flex-wrap">';
            h += '<button class="cl-btn-primary !h-9 text-xs" data-act="assess">' + icon('sparkles', 'w-4 h-4') + ' 熟练度评估</button>';
            h += '<button class="cl-btn-ghost !h-9 text-xs" data-act="notes">' + icon('book-open', 'w-4 h-4') + ' 基于笔记练习</button>';
            h += '<button class="cl-btn-ghost !h-9 text-xs" data-act="analogy">' + icon('lightbulb', 'w-4 h-4') + ' 举一反三练习</button>';
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
            main.innerHTML = h;
            main.querySelectorAll('[data-act]').forEach(function (b) {
                b.addEventListener('click', function () {
                    var act = b.getAttribute('data-act');
                    if (act === 'assess') startAssess(b);
                    else if (act === 'notes') startNotePractice(b);
                    else startAnalogyPractice(b);
                });
            });
            mountMemoryWidgets(main, 'kp', pid); // 每次整页重渲染后重新挂载取最新曲线/星值
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
            h += '<p class="text-sm font-medium text-cl-text mb-3 break-words">' + esc(q.question) + '</p>';
            h += '<div class="space-y-2">';
            (q.options || []).forEach(function (opt, i) {
                var letter = String.fromCharCode(65 + i);
                var checked = assess.ans[assess.idx] === letter ? ' checked' : '';
                h += '<label class="flex items-center gap-3 rounded-clbtn border border-cl-border px-3 py-2 cursor-pointer hover:bg-cl-bg">'
                    + '<input type="radio" name="kp-assess" value="' + letter + '"' + checked + '>'
                    + '<span class="text-[13px] text-cl-text-2"><strong>' + letter + '.</strong> ' + esc(opt) + '</span></label>';
            });
            h += '</div>';
            h += '<div class="flex items-center justify-between mt-5">';
            h += '<button class="cl-btn-ghost !h-8 text-xs" data-role="assess-prev"' + (assess.idx === 0 ? ' disabled' : '') + '>上一题</button>';
            h += '<button class="cl-btn-primary !h-8 text-xs" data-role="assess-next">' + (assess.idx === total - 1 ? '提交评估' : '下一题') + '</button></div>';
            p.innerHTML = h;
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
                    h += '<div class="rounded-clbtn bg-cl-bg px-3 py-2">'
                        + '<div class="flex items-start gap-2">' + (d.is_correct ? icon('check', 'w-4 h-4 text-cl-secondary shrink-0') : icon('x', 'w-4 h-4 text-cl-danger shrink-0'))
                        + '<p class="text-[13px] text-cl-text flex-1 break-words">' + esc(truncate(d.question, 80)) + '</p></div>'
                        + '<p class="text-xs text-cl-text-3 mt-1">你的答案：' + esc(d.user_answer || '未选') + '　正确答案：' + esc(d.correct_answer)
                        + (d.explanation ? '<br>解析：' + esc(d.explanation) : '') + '</p></div>';
                });
                h += '</div>';
                p.innerHTML = h;
                // 头部掌握度同步刷新（免重拉详情）
                if (state.det) {
                    state.det.mastery_score = score;
                    var ms = main.querySelector('[data-role="mastery-slot"]');
                    var ps = main.querySelector('[data-role="progress-slot"]');
                    if (ms) ms.innerHTML = masteryBadge(score);
                    if (ps) ps.innerHTML = progressBar(score);
                }
                mountMemoryWidgets(main, 'kp', pid); // 评审 c3 Major-1：评估复习落库后重挂面板（新曲线/星级/清 manual 标记）
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
        var prac = { qs: [], ans: [], idx: 0, title: '' };
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
            Promise.resolve(window.bridge.generatePointPractice(pid, source)).then(function (s) {
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
            h += '<p class="text-sm font-medium text-cl-text mb-3 break-words whitespace-pre-wrap">' + esc(q.question) + '</p>';
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
                            + '<span class="text-[13px] text-cl-text-2"><strong>' + letter + '.</strong> ' + esc(opt) + '</span></label>';
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
                    h += '<div class="rounded-clbtn bg-cl-bg px-3 py-2">'
                        + '<div class="flex items-start gap-2">' + (d.is_correct ? icon('check', 'w-4 h-4 text-cl-secondary shrink-0') : icon('x', 'w-4 h-4 text-cl-danger shrink-0'))
                        + '<p class="text-[13px] text-cl-text flex-1 break-words whitespace-pre-wrap">' + esc(truncate(d.question, 120)) + '</p></div>'
                        + '<p class="text-xs text-cl-text-3 mt-1">你的答案：' + esc(truncate(d.user_answer || '未答', 80)) + '　正确答案：' + esc(truncate(d.correct_answer, 80))
                        + (d.comment ? '<br>AI 点评：' + esc(d.comment) : '')
                        + (d.explanation ? '<br>解析：' + esc(d.explanation) : '') + '</p></div>';
                });
                h += '</div>';
                p.innerHTML = h;
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
                hint(wrong ? '提交完成：错题已入错题本，稍后可举一反三' : '全部答对！掌握度已更新');
            }).catch(function (e) { if (guard(p)) p.innerHTML = '<p class="text-sm text-cl-danger py-4">提交异常：' + esc(e.message) + '</p>'; });
        }
        function startNotePractice(btn) { startPointPractice(btn, 'notes', '基于笔记练习'); }
        function startAnalogyPractice(btn) { startPointPractice(btn, 'analogy', '举一反三练习'); }

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
