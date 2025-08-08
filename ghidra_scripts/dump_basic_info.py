#@category Analysis
# Script executed by Ghidra's analyzeHeadless to output simple function and string info.
import json
import sys

out_path = sys.argv[-1]
functions = [f.getName() for f in currentProgram.getFunctionManager().getFunctions(True)]
strings = []
listing = currentProgram.getListing()
iter = listing.getData(True)
while iter.hasNext():
    d = iter.next()
    dt = d.getDataType()
    if dt and dt.getName().lower().startswith("string"):
        try:
            strings.append(str(d.getValue()))
        except Exception:
            pass
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump({'functions': functions, 'strings': strings}, f)
