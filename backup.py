import sqlite3, shutil, zipfile, json
from pathlib import Path
from datetime import datetime, timedelta

ROOT=Path(__file__).resolve().parent
DB=ROOT/"data"/"cookbook.db"
UPLOADS=ROOT/"uploads"
BACKUPS=ROOT/"backups"
BACKUPS.mkdir(exist_ok=True)
stamp=datetime.now().strftime("%Y-%m-%d_%H%M")
dest=BACKUPS/stamp
dest.mkdir()
src=sqlite3.connect(DB)
dst=sqlite3.connect(dest/"cookbook.db")
with dst: src.backup(dst)
dst.close();src.close()
if UPLOADS.exists():
    with zipfile.ZipFile(dest/"uploads.zip","w",zipfile.ZIP_DEFLATED) as z:
        for p in UPLOADS.rglob("*"):
            if p.is_file(): z.write(p,p.relative_to(UPLOADS))
for folder in BACKUPS.iterdir():
    if folder.is_dir():
        try:
            dt=datetime.strptime(folder.name,"%Y-%m-%d_%H%M")
            if datetime.now()-dt>timedelta(days=45): shutil.rmtree(folder)
        except: pass
print(f"Backup created: {dest}")
