import re, io
p = r'e:\LLM\LectureLearnLoop\server\templates\pages\online_course_notes.html'
lines = io.open(p, encoding='utf-8').read().splitlines()
pat = re.compile(r'<script|</script>|^\s*function |initTextSelectionContextMenu|^\s{0,4}\}\)\(\);')
for i, l in enumerate(lines[10320:], start=10321):
    if pat.search(l):
        print(i, '|', l.strip()[:110])
