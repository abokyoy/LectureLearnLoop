/* MdRender：Markdown 数学公式渲染公共件（2026-10-13）
 * 背景：错题题干/答案/解析由智能分析与 OCR 录入后大量携带 $…$ / $$…$$ LaTeX 公式，
 *       而 marked 不识别公式且会把 `$x_1$…$x_2$` 的下划线咬成 <em>、反斜杠当转义丢弃，
 *       事后直接跑 KaTeX 已拿不到完整公式串。故必须「marked 前占位保护 → sanitize 后 KaTeX 回填」。
 * 用法（与既有 MD 管线组合，不替换 marked/DOMPurify）：
 *   var ex = MdRender.extract(mdSrc);              // { text: 含占位符的 MD, slots: [公式] }
 *   el.innerHTML = DOMPurify.sanitize(marked.parse(ex.text));
 *   MdRender.applyMath(el, ex.slots);              // sanitize 之后调用：公式渲染的是 KaTeX 可信产物
 * 降级链（核心功能降级兜底规范）：
 *   - window.katex 缺失（vendor 脚本加载失败）→ 公式还原为原文 $…$ 纯文本展示；
 *   - 单条公式语法错误（OCR 误识别）→ KaTeX throwOnError:false 红字显示错误，不中断整段渲染；
 *   - 调用方未接入（marked 缺失走 textContent 回退）→ 不受影响，无残留占位符（回退用的是原始 MD 串）。
 * 定界符口径（与 Vditor/数学作业常见写法对齐）：
 *   - 块级：$$…$$、\[…\]；行内：$…$、\(…\)
 *   - \$ 为字面美元符（转义保护）；``` 围栏与 `行内代码` 内的 $ 不当公式；
 *   - 防货币误判：$ 后紧跟数字（如 "$5 和 $6"）不当公式——数学题极少以纯数字开头写行内公式，代价可控。
 */
(function () {
    'use strict';

    var PH_OPEN = '\uE000';   // 私用区字符做占位边界：marked/DOMPurify 均原样保留文本字符
    var PH_CLOSE = '\uE001';
    var ESC_DOLLAR = '\uE002'; // 预处理：\$ 先摘出，防止被当作定界符
    // 必须带 g：applyMath 内靠 exec 逐次推进 lastIndex 遍历占位符，无 g 会同一位置无限匹配（UI 实测卡死页面的根因）
    var PH_SPLIT = /\uE000(\d+)\uE001/g;

    function restoreEsc(s) {
        // 还原字面 \$（可能位于占位符分割后的任意文本段）
        return s.indexOf(ESC_DOLLAR) >= 0 ? s.split(ESC_DOLLAR).join('\\$') : s;
    }

    /* extract(mdText) -> { text, slots }
     * slots[i] = { body: 公式体, display: 是否块级, raw: 含定界符原文（无 katex 时回退显示用） } */
    function extract(mdText) {
        var slots = [];
        var src = String(mdText || '').split('\\$').join(ESC_DOLLAR);

        function ph(body, display, raw) {
            slots.push({ body: body, display: display, raw: raw });
            return PH_OPEN + (slots.length - 1) + PH_CLOSE;
        }
        function protect(t) {
            // 顺序敏感：先 \[..\] 与 $$..$$ 再 \(..\) 最后单 $，避免块级被行内规则截胡
            t = t.replace(/\\\[([\s\S]+?)\\\]/g, function (m, b) { return ph(b.trim(), true, m); });
            t = t.replace(/\$\$([\s\S]+?)\$\$/g, function (m, b) { return ph(b.trim(), true, m); });
            t = t.replace(/\\\(([\s\S]+?)\\\)/g, function (m, b) { return ph(b.trim(), false, m); });
            t = t.replace(/\$([^\s$][^$\n]*?[^\s$]|[^\s$])\$(?!\d)/g, function (m, b) {
                if (/^\d/.test(b)) return m; // 货币防误判："花了 $5 和 $6" 不配公式
                return ph(b, false, m);
            });
            return t;
        }

        // 代码段保护：split 捕获组奇数位为 ```/~~~ 围栏与行内 `code`，原样保留不做公式提取
        var segs = src.split(/(```[\s\S]*?(?:```|$)|~~~[\s\S]*?(?:~~~|$)|`[^`\n]*`)/);
        var out = '';
        for (var i = 0; i < segs.length; i++) {
            out += (i % 2 === 1) ? segs[i] : protect(segs[i]);
        }
        return { text: out, slots: slots };
    }

    function slotNode(s) {
        if (!s) return null;
        if (typeof window.katex === 'undefined' || !window.katex.renderToString) {
            return document.createTextNode(restoreEsc(s.raw)); // 无 katex：原文回退
        }
        try {
            var span = document.createElement('span');
            span.innerHTML = window.katex.renderToString(
                String(s.body).split(ESC_DOLLAR).join('\\$'),
                { displayMode: !!s.display, throwOnError: false, output: 'html' }
            );
            return span;
        } catch (e) {
            return document.createTextNode(restoreEsc(s.raw)); // 极端异常也不留占位符
        }
    }

    /* applyMath(el, slots)：sanitize/innerHTML 之后调用，文本节点内替换占位符为 KaTeX 产物；
     * 顺带还原全文 \$ 转义（无公式时也要跑，否则 E002 字符会显示成豆腐块）。
     * 注意：必须两阶段（先收集后替换）——遍历中 replaceChild 会让 TreeWalker 的
     * currentNode 脱离文档导致遍历提前终止，多段落容器只剩首个节点被处理（UI 实测发现）。 */
    function applyMath(el, slots) {
        if (!el || !el.ownerDocument) return;
        slots = slots || [];
        var walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, {
            acceptNode: function (n) {
                var v = n.nodeValue || '';
                return (v.indexOf(PH_OPEN) >= 0 || v.indexOf(ESC_DOLLAR) >= 0) ? 1 /* ACCEPT */ : 2 /* REJECT */;
            }
        }, false);
        var targets = [], tn;
        while ((tn = walker.nextNode())) targets.push(tn);
        for (var ti = 0; ti < targets.length; ti++) {
            var node = targets[ti];
            if (!node.isConnected) continue; // 理论上不会发生（替换只影响当前节点），防御性跳过
            PH_SPLIT.lastIndex = 0; // 防御：进入新文本节点前归零，杜绝跨节点残留游标
            var m = PH_SPLIT.exec(node.nodeValue);
            if (!m) { node.nodeValue = restoreEsc(node.nodeValue); continue; } // 无占位符段：只还原转义
            var v = node.nodeValue, frag = document.createDocumentFragment(), pos = 0;
            PH_SPLIT.lastIndex = 0; // 关键：上方 m=exec 已推进游标，内层遍历前必须再归零，否则首个占位符被漏掉
            var mm;
            while ((mm = PH_SPLIT.exec(v))) {
                frag.appendChild(document.createTextNode(restoreEsc(v.slice(pos, mm.index))));
                var idx = Number(mm[1]);
                var n2 = idx < slots.length ? slotNode(slots[idx]) : null;
                // 越界（用户正文撞码 \uE000数字\uE001 的极罕见场景）时保留原串，不丢内容（CodeReview Minor-4）
                frag.appendChild(n2 || document.createTextNode(mm[0]));
                pos = mm.index + mm[0].length;
            }
            frag.appendChild(document.createTextNode(restoreEsc(v.slice(pos))));
            node.parentNode.replaceChild(frag, node);
        }
    }

    window.MdRender = { extract: extract, applyMath: applyMath };
})();
