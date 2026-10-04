import re, io
s = io.open('static/icons/lucide-sprite.svg', encoding='utf-8').read()
ids = sorted(set(re.findall(r'id="li-([a-z0-9-]+)"', s)))
io.open('logs/sprite_ids.txt', 'w', encoding='utf-8').write('\n'.join(ids))
print(len(ids))
