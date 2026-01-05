from pathlib import Path
text = Path('templates/stream/watch_video.html').read_text(encoding='utf-8')
for line in text.splitlines():
    if 'Voltar' in line:
        print(line)
    if 'não' in line:
        print(line)
print(text.count('catálogo'))
print(text.count('catálogo'.replace('á','a')))
