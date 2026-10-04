/*
 * widgets.js — 第2轮共享 UI 组件（星值控件 / 熟练度滑杆 / 熟练度曲线）
 * 唯一实现，禁止各页面重复造轮子（架构原则·公共函数注册制）。
 * 挂载为 window.LLStars / window.LLSlider / window.LLCurve，零外部依赖（纯 SVG）。
 *
 * 数值约定（与后端 fsrs 方案一致）：
 *  - 难度/重要度：存储 0-10 分 = 星×2，5 星制半星步进；最低 0.5 星(=1)，上限 5 星(=10)，0 不允许。
 *  - 熟练度：0-100；-1/null/undefined = 未评估（灰），0 = 完全忘记（不得当未评估处理）。
 */
(function (global) {
    'use strict';

    function clamp(v, lo, hi) { v = Number(v); if (isNaN(v)) return lo; return Math.min(hi, Math.max(lo, v)); }

    /* ---------------- LLStars：五角星（半星步进，可点可键盘） ---------------- */
    var LLStars = {
        /**
         * mount(container, {value, onChange, readonly, label})
         *  value: 0-10 存储分；onChange(newStored 0-10) 用户变更后回调（0 不会出现）。
         */
        mount: function (container, opts) {
            opts = opts || {};
            var el = typeof container === 'string' ? document.querySelector(container) : container;
            if (!el) return null;
            var value = clamp(opts.value == null ? 5 : opts.value, 1, 10);
            var readonly = !!opts.readonly;
            el.classList.add('ll-stars');
            el.style.display = 'inline-flex';
            el.style.alignItems = 'center';
            el.style.gap = '2px';
            el.setAttribute('role', 'slider');
            el.setAttribute('aria-valuemin', '1');
            el.setAttribute('aria-valuemax', '10');
            el.setAttribute('aria-valuenow', String(value));
            if (!readonly) el.setAttribute('tabindex', '0');
            var svgNS = 'http://www.w3.org/2000/svg';
            var stars = [];
            function starPath(i) {
                // 每颗星：左半点击 = 该星 -0.5 星(即值 i*2-1)，右半 = 整星(i*2+2 上限内)
                var g = document.createElementNS(svgNS, 'g');
                var left = document.createElementNS(svgNS, 'rect');
                left.setAttribute('x', i * 18); left.setAttribute('y', 0);
                left.setAttribute('width', 9); left.setAttribute('height', 16);
                left.setAttribute('fill', 'transparent');
                var right = document.createElementNS(svgNS, 'rect');
                right.setAttribute('x', i * 18 + 9); right.setAttribute('y', 0);
                right.setAttribute('width', 9); right.setAttribute('height', 16);
                right.setAttribute('fill', 'transparent');
                g.appendChild(left); g.appendChild(right);
                if (!readonly) {
                    left.style.cursor = 'pointer'; right.style.cursor = 'pointer';
                    left.addEventListener('click', function () { set(i * 2 + 1); });   // 半星
                    right.addEventListener('click', function () { set(i * 2 + 2); });  // 整星
                }
                return g;
            }
            var svg = document.createElementNS(svgNS, 'svg');
            svg.setAttribute('width', 90); svg.setAttribute('height', 16);
            svg.setAttribute('viewBox', '0 0 90 16');
            function drawStar(i, mode) { // mode: 'full' | 'half' | 'empty'
                var p = document.createElementNS(svgNS, 'path');
                var cx = i * 18 + 9;
                p.setAttribute('d', 'M' + cx + ',1 L' + (cx + 2.6) + ',6.1 L8.3+0'.replace('8.3+0', String(cx + 7.6)) + ',6.6 L' + (cx + 4) + ',10.6 L' + (cx + 4.9) + ',15 L' + cx + ',12.4 L' + (cx - 4.9) + ',15 L' + (cx - 4) + ',10.6 L' + (cx - 7.6) + ',6.6 L' + (cx - 2.6) + ',6.1 Z');
                p.setAttribute('fill', mode === 'full' ? '#F59E0B' : (mode === 'half' ? '#FBBF24' : '#D1D5DB'));
                svg.appendChild(p);
            }
            function render() {
                while (svg.firstChild) svg.removeChild(svg.firstChild);
                for (var i = 0; i < 5; i++) {
                    var starVal = (value - i * 2) / 2; // 0..2
                    drawStar(i, starVal >= 1.75 ? 'full' : (starVal >= 0.75 ? 'half' : 'empty'));
                }
                for (var j = 0; j < 5; j++) svg.appendChild(starPath(j));
                el.setAttribute('aria-valuenow', String(value));
                if (labelEl) labelEl.textContent = opts.label ? (opts.label + ' ') + (value / 2) + '★' : (value / 2) + '★';
            }
            function set(v) {
                v = clamp(Math.round(v), 1, 10);
                if (v === value) return;
                value = v; render();
                if (typeof opts.onChange === 'function') opts.onChange(value);
            }
            var labelEl = document.createElement('span');
            labelEl.style.marginLeft = '6px';
            labelEl.style.fontSize = '12px';
            labelEl.style.color = '#6B7280';
            el.innerHTML = '';
            el.appendChild(svg);
            if (!readonly) el.appendChild(labelEl);
            el.addEventListener('keydown', function (e) {
                if (readonly) return;
                if (e.key === 'ArrowRight') { set(value + 1); e.preventDefault(); }
                if (e.key === 'ArrowLeft') { set(value - 1); e.preventDefault(); }
            });
            render();
            return { set: function (v) { value = clamp(Math.round(v), 1, 10); render(); }, get: function () { return value; } };
        }
    };

    /* ---------------- LLSlider：熟练度滑杆（用户手动=最高优先级） ---------------- */
    var LLSlider = {
        /**
         * mount(container, {value, onCommit, labelText})
         *  value: -1..100（-1=未评估）；onCommit(v 0-100) 在用户松手/释放时触发（需二次确认文案）。
         */
        mount: function (container, opts) {
            opts = opts || {};
            var el = typeof container === 'string' ? document.querySelector(container) : container;
            if (!el) return null;
            var v = opts.value == null ? -1 : clamp(opts.value, -1, 100);
            el.classList.add('ll-mastery-slider');
            el.innerHTML =
                '<div style="display:flex;align-items:center;gap:8px;">' +
                '<input type="range" min="0" max="100" step="1" style="flex:1;accent-color:#EF4444;">' +
                '<span class="ll-ms-val" style="min-width:56px;font-size:12px;color:#374151;"></span>' +
                '</div>' +
                '<div class="ll-ms-hint" style="font-size:11px;color:#9CA3AF;margin-top:2px;"></div>';
            var input = el.querySelector('input');
            var valEl = el.querySelector('.ll-ms-val');
            var hintEl = el.querySelector('.ll-ms-hint');
            function paint() {
                if (v < 0) { valEl.textContent = '未评估'; hintEl.textContent = '拖动滑杆可手动设定熟练度（手动设定优先级最高，下次复习后恢复自动派生）'; input.value = 0; }
                else { valEl.textContent = v + ' 分'; hintEl.textContent = '手动设定优先级最高，下次复习后恢复自动派生'; input.value = v; }
            }
            input.addEventListener('input', function () { v = Number(input.value); paint(); });
            input.addEventListener('change', function () {
                v = clamp(Math.round(Number(input.value)), 0, 100);
                if (typeof opts.onCommit === 'function') opts.onCommit(v);
                paint();
            });
            paint();
            return { set: function (nv) { v = nv; paint(); } };
        }
    };

    /* ---------------- LLCurve：熟练度曲线（mastery 与 retrievability 双线，纯 SVG） ---------------- */
    var LLCurve = {
        /**
         * draw(container, {points:[{ts, mastery, retrievability(0-1 可空)}], width, height})
         */
        draw: function (container, opts) {
            opts = opts || {};
            var el = typeof container === 'string' ? document.querySelector(container) : container;
            if (!el) return;
            var W = opts.width || 320, H = opts.height || 120, P = 24;
            var pts = (opts.points || []).filter(function (p) { return p && p.mastery != null; });
            el.innerHTML = '';
            if (pts.length < 1) { el.innerHTML = '<div style="font-size:12px;color:#9CA3AF;">暂无熟练度记录</div>'; return; }
            var svgNS = 'http://www.w3.org/2000/svg';
            var svg = document.createElementNS(svgNS, 'svg');
            svg.setAttribute('width', W); svg.setAttribute('height', H);
            var n = pts.length;
            function X(i) { return P + i * (W - 2 * P) / Math.max(1, n - 1); }
            function Y(val) { return H - P - (clamp(val, 0, 100) / 100) * (H - 2 * P); }
            // 轴
            var axis = document.createElementNS(svgNS, 'path');
            axis.setAttribute('d', 'M' + P + ',' + (H - P) + ' L' + (W - P) + ',' + (H - P) + ' M' + P + ',' + (H - P) + ' L' + P + ',' + P);
            axis.setAttribute('stroke', '#E5E7EB'); axis.setAttribute('fill', 'none');
            svg.appendChild(axis);
            function poly(get, color, dash) {
                var d = '';
                for (var i = 0; i < n; i++) { var y = get(pts[i]); if (y == null) continue; d += (d ? ' L' : 'M') + X(i) + ',' + y; }
                if (!d) return;
                var p = document.createElementNS(svgNS, 'path');
                p.setAttribute('d', d); p.setAttribute('stroke', color); p.setAttribute('fill', 'none'); p.setAttribute('stroke-width', '2');
                if (dash) p.setAttribute('stroke-dasharray', '4 3');
                svg.appendChild(p);
            }
            poly(function (pt) { return Number(pt.mastery); }, '#EF4444', false);
            poly(function (pt) { return pt.retrievability != null ? Number(pt.retrievability) * 100 : null; }, '#3B82F6', true);
            for (var i = 0; i < n; i++) {
                var c = document.createElementNS(svgNS, 'circle');
                c.setAttribute('cx', X(i)); c.setAttribute('cy', Y(pts[i].mastery)); c.setAttribute('r', 2.5);
                c.setAttribute('fill', '#EF4444');
                var t = document.createElementNS(svgNS, 'title');
                t.textContent = (pts[i].ts || '') + ' 熟练度 ' + pts[i].mastery + (pts[i].retrievability != null ? ' / 记忆保留 ' + Math.round(pts[i].retrievability * 100) + '%' : '');
                c.appendChild(t); svg.appendChild(c);
            }
            var legend = document.createElement('div');
            legend.style.cssText = 'font-size:11px;color:#6B7280;margin-top:2px;';
            legend.innerHTML = '<span style="color:#EF4444;">— 熟练度(100×R)</span>　<span style="color:#3B82F6;">-- 复习时点记忆保留度</span>';
            el.appendChild(svg); el.appendChild(legend);
        }
    };

    global.LLStars = LLStars;
    global.LLSlider = LLSlider;
    global.LLCurve = LLCurve;
})(window);
