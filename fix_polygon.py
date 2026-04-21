content = open('notebook_cells/cell10_final_output.py', encoding='utf-8').read()
old = 'xs = [p.get("x", p[0]) if isinstance(p, dict) else p[0] for p in data]'
new = 'xs = [p["x"] if isinstance(p, dict) else p[0] for p in data]'
content = content.replace(old, new)
old2 = 'ys = [p.get("y", p[1]) if isinstance(p, dict) else p[1] for p in data]'
new2 = 'ys = [p["y"] if isinstance(p, dict) else p[1] for p in data]'
content = content.replace(old2, new2)
open('notebook_cells/cell10_final_output.py', 'w', encoding='utf-8').write(content)
print('Fixed')
