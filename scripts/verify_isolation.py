"""Read-only source fingerprints + original container identities, output in this project."""
import hashlib
import json
import subprocess

from personal_rag.config import ROOT

manifest = json.loads((ROOT / "docs/EXTRACTION.json").read_text(encoding="utf-8"))
sources = []
for item in manifest["files"]:
    from pathlib import Path
    original = hashlib.sha256(Path(item["source"]).read_bytes()).hexdigest()
    copied = hashlib.sha256((ROOT / item["target"]).read_bytes()).hexdigest()
    sources.append({"source": item["source"], "original_unchanged": original == item["sha256"],
                    "verbatim_copy": copied == item["sha256"]})
baseline = json.loads((ROOT / "output/container-baseline.json").read_text(encoding="utf-8"))
process = subprocess.run(["docker", "ps", "--format", "{{json .}}"], check=True, capture_output=True, encoding="utf-8")
current = {row["Names"]: row for row in (json.loads(line) for line in process.stdout.splitlines())}
unchanged = all(row["Names"] in current and current[row["Names"]]["ID"] == row["ID"] and
                current[row["Names"]]["Image"] == row["Image"] for row in baseline)
report = {"source_checks": sources, "baseline_running_containers": len(baseline),
          "original_running_container_ids_and_images_unchanged": unchanged,
          "new_containers": sorted(set(current) - {row["Names"] for row in baseline}),
          "limits": "Checks extracted source fingerprints and running-container identities, not every enterprise file or database row."}
(ROOT / "output/isolation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
assert unchanged and all(row["original_unchanged"] and row["verbatim_copy"] for row in sources)
print(json.dumps({"verified": True, "source_files": len(sources), "original_containers": len(baseline),
                  "new_containers": report["new_containers"]}, ensure_ascii=False))
