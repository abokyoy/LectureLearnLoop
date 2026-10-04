# -*- coding: utf-8 -*-
p = r'e:\LLM\LectureLearnLoop\docs\掉坑笔记\掉坑笔记.md'
s = open(p, encoding='utf-8').read()
s = s.replace('### 【P032】2026-10-02', '### P032：2026-10-02')
open(p, 'w', encoding='utf-8').write(s)
print('fmt ok')
