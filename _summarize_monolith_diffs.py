from pathlib import Path
import difflib
import json

root = Path(r"c:\Users\Protodesign\Desktop\SMART INTERO\SMART")
mono = root / "SMART_DSS_MONOLIT" / "SMART-DSS-NEW"
micro = root / "SMART-DSS-MICROSERVICES"
report = json.loads((micro / "MONOLITH_DIFF_REPORT.json").read_text(encoding="utf-8"))
files = report["modified_common"]

out = []
for rel in files:
    p1 = mono / rel
    p2 = micro / rel
    if not (p1.exists() and p2.exists()):
        continue
    a = p1.read_text(encoding="utf-8", errors="ignore").splitlines()
    b = p2.read_text(encoding="utf-8", errors="ignore").splitlines()
    sm = difflib.SequenceMatcher(None, a, b)
    ratio = sm.ratio()
    changes = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "equal":
            changes += (i2 - i1) + (j2 - j1)
    out.append({"file": rel, "similarity": round(ratio, 4), "change_size": changes, "mono_lines": len(a), "micro_lines": len(b)})

out.sort(key=lambda x: x["change_size"], reverse=True)
(micro / "MONOLITH_DIFF_SUMMARY.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
print("written", len(out))
for row in out[:15]:
    print(f"{row['change_size']:5d} | {row['similarity']:.3f} | {row['file']}")
