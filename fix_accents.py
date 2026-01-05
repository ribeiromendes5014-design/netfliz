from pathlib import Path
path = Path('templates/stream/watch_video.html')
text = path.read_text(encoding='utf-8')
text = text.replace('catǭlogo', 'catálogo')
text = text.replace('nǜo', 'não')
path.write_text(text, encoding='utf-8')
