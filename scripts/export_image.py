"""Export the application image only; user configuration and data stay outside it."""
import gzip
import hashlib
import json
import shutil
import subprocess

from personal_rag.config import ROOT

image = "personal-rag:0.1.0"
directory = ROOT / "output"
directory.mkdir(exist_ok=True)
destination = directory / "personal-rag-0.1.0-linux-amd64.tar.gz"
info = json.loads(subprocess.check_output(["docker", "image", "inspect", image], encoding="utf-8"))[0]
if info["Os"] != "linux" or info["Architecture"] != "amd64":
    raise SystemExit("当前导出文件名仅用于 linux/amd64；请为其他架构调整文件名")
with subprocess.Popen(["docker", "image", "save", image], stdout=subprocess.PIPE) as process:
    with gzip.open(destination, "wb", compresslevel=3) as stream:
        shutil.copyfileobj(process.stdout, stream, length=1024 * 1024)
    if process.wait() != 0:
        destination.unlink(missing_ok=True)
        raise SystemExit("镜像导出失败")
hasher = hashlib.sha256()
with destination.open("rb") as stream:
    for block in iter(lambda: stream.read(1024 * 1024), b""):
        hasher.update(block)
metadata = {"image": image, "id": info["Id"], "platform": "linux/amd64", "bytes": destination.stat().st_size,
            "sha256": hasher.hexdigest(), "file": destination.name}
destination.with_suffix(destination.suffix + ".json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
print(json.dumps(metadata, indent=2))
