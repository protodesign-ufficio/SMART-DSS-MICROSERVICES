from pathlib import Path
import hashlib
import json

root = Path(r"c:\Users\Protodesign\Desktop\SMART INTERO\SMART")
mono = root / "SMART_DSS_MONOLIT" / "SMART-DSS-NEW"
micro = root / "SMART-DSS-MICROSERVICES"

IGNORE_DIRS = {
    ".git", "__pycache__", ".pytest_cache", "node_modules", "copernicus-data", "docs", "old-ignore"
}
IGNORE_FILES = {
    "FULL_ENDPOINT_AUDIT.md", "REGRESSION_OLD_NEW.md", "GAP_ANALYSIS_OLD_vs_NEW.md",
    "ARCHITETTURA_ENDPOINT_DB_MAP.md", "AUDIT_FK_SPLIT_REPORT.md"
}


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def scan(base: Path):
    out = {}
    for p in base.rglob("*"):
        if p.is_dir():
            continue
        rel = p.relative_to(base)
        if any(part in IGNORE_DIRS for part in rel.parts):
            continue
        if rel.name in IGNORE_FILES:
            continue
        out[str(rel).replace("\\", "/")] = file_hash(p)
    return out

mono_map = scan(mono)
micro_map = scan(micro)

mono_files = set(mono_map)
micro_files = set(micro_map)

added_in_mono = sorted(mono_files - micro_files)
removed_from_mono = sorted(micro_files - mono_files)
common = mono_files & micro_files
modified = sorted([f for f in common if mono_map[f] != micro_map[f]])


def top_bucket(path: str) -> str:
    return path.split("/", 1)[0] if "/" in path else "(root)"

by_bucket = {}
for f in modified:
    by_bucket[top_bucket(f)] = by_bucket.get(top_bucket(f), 0) + 1

report = {
    "monolith_path": str(mono),
    "micro_path": str(micro),
    "added_in_monolith": added_in_mono,
    "removed_vs_monolith": removed_from_mono,
    "modified_common": modified,
    "modified_by_bucket": dict(sorted(by_bucket.items(), key=lambda x: x[0]))
}

out_file = micro / "MONOLITH_DIFF_REPORT.json"
out_file.write_text(json.dumps(report, indent=2), encoding="utf-8")

print("added_in_monolith", len(added_in_mono))
print("removed_vs_monolith", len(removed_from_mono))
print("modified_common", len(modified))
print("report", out_file)
