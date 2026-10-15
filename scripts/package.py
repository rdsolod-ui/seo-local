"""Create a source-only archive: no DB, credentials, caches, or third-party runtime."""
from pathlib import Path
import zipfile
import subprocess

root = Path(__file__).resolve().parent.parent
target = root / "artifacts" / "seo-local-source.zip"
target.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
    for rel in subprocess.check_output(['git','ls-files','-z'],cwd=root).decode().split('\0'):
        if rel:
            archive.write(root/rel, 'seo-local/'+rel)
print(target)
