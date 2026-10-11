/* md_render.js 离线断言（node 直跑）：公式抽取/保护/回退的纯字符串逻辑。
 * applyMath 依赖 DOM+KaTeX，由 UI harness（Playwright）在浏览器端断言 .katex 产物。
 * 运行：node server/tests/md_render_node_test.js
 */
'use strict';
const fs = require('fs');
const path = require('path');
const assert = require('assert');

global.window = {};
const code = fs.readFileSync(path.join(__dirname, '../static/js/md_render.js'), 'utf8');
eval(code);
const MdRender = global.window.MdRender;
assert(MdRender && MdRender.extract && MdRender.applyMath, 'MdRender 导出完整');

let pass = 0, fail = 0;
function t(name, fn) {
    try { fn(); pass++; console.log('PASS', name); }
    catch (e) { fail++; console.log('FAIL', name, '->', e.message); }
}

t('用户样例：10 条行内公式全部抽取且不残 $', function () {
    const sample = '由题意，一个根小于 2，即 $-m < 2$，解得 $m > -2$，结合前提 $m \\geq -2$，得 $m > -2$。'
        + '② 当 $m < -2$ 时，$|m+2| = -(m+2)$，则 $x = \\frac{2 - m \\pm (-(m+2))}{2}$，'
        + '由题意与前提矛盾，无解。综上，$m > -2$，又 $m$ 为整数，故 $m \\geq -1$。';
    const ex = MdRender.extract(sample);
    assert.strictEqual(ex.slots.length, 10);
    assert.ok(ex.text.indexOf('$') < 0, '保护后文本不含裸 $');
    assert.ok(ex.text.indexOf('\uE000') >= 0, '含占位符');
    assert.ok(ex.slots.every(s => s.display === false), '行内式 display=false');
    assert.ok(ex.slots[6].body.indexOf('\\frac{2 - m \\pm (-(m+2))}{2}') >= 0, 'frac 完整保留（反斜杠未被吞）');
});

t('连续成对 $a$，$b$ 配对正确（用户样例核心症状）', function () {
    const ex = MdRender.extract('$x_1 = -m$，$x_2 = 2$');
    assert.strictEqual(ex.slots.length, 2);
    assert.strictEqual(ex.slots[0].body, 'x_1 = -m');
    assert.strictEqual(ex.slots[1].body, 'x_2 = 2');
});

t('下划线/星号在公式内不被 MD 语义化破坏（extract 后移交占位符）', function () {
    const ex = MdRender.extract('计算 $a_1 + a_2$ 与 $b^*$');
    assert.strictEqual(ex.slots.length, 2);
    assert.ok(ex.text.indexOf('_') < 0 && ex.text.indexOf('*') < 0, '公式体外无裸 _ 与 * 诱因');
});

t('块级 $$…$$ 跨行 display=true', function () {
    const ex = MdRender.extract('前提：\n$$\nx = \\frac{-b \\pm \\sqrt{b^2-4ac}}{2a}\n$$\n综上');
    assert.strictEqual(ex.slots.length, 1);
    assert.strictEqual(ex.slots[0].display, true);
    assert.ok(ex.slots[0].body.indexOf('\\sqrt{b^2-4ac}') >= 0);
});

t('\\[..\\] 与 \\(..\\) 定界符', function () {
    const ex = MdRender.extract('\\[a+b\\] 以及 \\(c+d\\)');
    assert.strictEqual(ex.slots.length, 2);
    assert.strictEqual(ex.slots[0].display, true);
    assert.strictEqual(ex.slots[1].display, false);
});

t('货币防误判：$5 和 $6 不当公式', function () {
    const ex = MdRender.extract('花了 $5 和 $6 元');
    assert.strictEqual(ex.slots.length, 0);
    assert.ok(ex.text.indexOf('$') >= 0, '原文保留');
});

t('行内代码与围栏代码内的 $ 不提取', function () {
    const ex = MdRender.extract('用 `$x$` 表示：\n```\n$$a+b$$\n```\n结束 $y$');
    assert.strictEqual(ex.slots.length, 1);
    assert.strictEqual(ex.slots[0].body, 'y');
});

t('\\$ 转义：不作为定界符', function () {
    const ex = MdRender.extract('价格 \\$5，公式 $x^2$ 混排');
    assert.strictEqual(ex.slots.length, 1);
    assert.strictEqual(ex.slots[0].body, 'x^2');
    assert.ok(ex.text.indexOf('\uE002') >= 0, '\\$ 已摘出为转义字符，applyMath 阶段还原');
});

t('未闭合围栏：兜到文末不误配', function () {
    const ex = MdRender.extract('```json\n$x$\n未闭合');
    assert.strictEqual(ex.slots.length, 0);
});

t('空串与无公式文本', function () {
    assert.deepStrictEqual(MdRender.extract('').slots, []);
    assert.strictEqual(MdRender.extract('普通题干没有公式').text, '普通题干没有公式');
});

console.log('finish: pass=' + pass + ' fail=' + fail);
process.exit(fail ? 1 : 0);
