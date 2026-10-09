import re

with open("public/index.html", encoding="utf-8") as f:
    html = f.read()
with open("public/js/app.js", encoding="utf-8") as f:
    js = f.read()

ids = re.findall(r'document\.getElementById\(["\']([^"\']+)["\']\)', js)
print("Total getElementById in js:", len(ids))
missing = []
for i in ids:
    if f'id="{i}"' not in html and f"id='{i}'" not in html:
        missing.append(i)

print("Missing IDs:", missing)
