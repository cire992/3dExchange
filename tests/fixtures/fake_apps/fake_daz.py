"""Stands in for DAZStudio.exe in tests. It cannot run DazScript, so it reads the paths the
generated wrapper names, writes a result echoing the arguments (or an error if the script file
says FAIL), then keeps running like a Daz Studio that does not exit by itself."""

import json
import re
import sys
import time
from pathlib import Path

wrapper = Path(sys.argv[-1]).read_text(encoding="utf-8")
paths = dict(re.findall(r"var (argsPath|resultPath) = (\"[^\"]*\")", wrapper))
script = json.loads(re.search(r"include\((\"[^\"]*\")\)", wrapper).group(1))
job = json.loads(Path(json.loads(paths["argsPath"])).read_text(encoding="utf-8"))
if "FAIL" in Path(script).read_text(encoding="utf-8"):
    outcome = {"ok": False, "error": "Error: the script failed on purpose"}
else:
    outcome = {"ok": True, "result": {"echo": job["args"], "flags": sys.argv[1:-1]}}
Path(json.loads(paths["resultPath"])).write_text(json.dumps(outcome), encoding="utf-8")
time.sleep(120)  # Daz Studio left open: the bridge must close it
