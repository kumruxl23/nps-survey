import re
content = open('notebook_cells/cell03_template.py', encoding='utf-8').read()
strings = re.findall(r'"""(.*?)"""', content, re.DOTALL)
tc = ' '.join(strings)
for name in ['metaOverrides','getEffectiveMeta','META_DEFS','buildMetaPanel','syncAnnMeta','blobCache','createObjectURL','meta-panel','metadata_snapshot','_metadata_propagation']:
    c = tc.count(name)
    print(f"  {name}: {'CLEAN' if c==0 else f'FOUND {c}x'}")
