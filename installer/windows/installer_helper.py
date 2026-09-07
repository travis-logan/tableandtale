from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sqlite3
import sys
import traceback
from pathlib import Path


def user_snapshot(db_path: str) -> dict:
    conn = sqlite3.connect(db_path, timeout=30)
    try:
        rows = conn.execute(
            """
            SELECT id, username, display_name, COALESCE(email,''), password_hash,
                   role, active, created_at, COALESCE(last_login_at,'')
            FROM users ORDER BY id
            """
        ).fetchall()
        payload = json.dumps(rows, separators=(",", ":"), ensure_ascii=False)
        fp = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        try:
            schema_row = conn.execute(
                "SELECT value FROM schema_meta WHERE key='schema_version'"
            ).fetchone()
            schema_version = schema_row[0] if schema_row else "unknown"
        except sqlite3.Error:
            schema_version = "unknown"
        return {
            "ok": True,
            "user_count": len(rows),
            "user_fingerprint": fp,
            "schema_version": str(schema_version),
        }
    finally:
        conn.close()


def backup_db(src: str, dest: str) -> dict:
    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(src, timeout=30)
    try:
        try:
            source.execute("PRAGMA wal_checkpoint(FULL)")
        except sqlite3.Error:
            pass
        target = sqlite3.connect(dest, timeout=30)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()
    info = user_snapshot(dest)
    info["backup_path"] = dest
    return info


def preflight(app_path: str, db_path: str, data_dir: str, upload_dir: str) -> dict:
    os.environ["COOKBOOK_DB_PATH"] = db_path
    os.environ["COOKBOOK_DATA_DIR"] = data_dir
    os.environ["COOKBOOK_UPLOAD_DIR"] = upload_dir
    os.environ["COOKBOOK_HOST"] = "127.0.0.1"
    spec = importlib.util.spec_from_file_location("table_tale_preflight", app_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load Table & Tale app module for migration preflight.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return user_snapshot(db_path)


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    p_info = sub.add_parser("db-info")
    p_info.add_argument("--db", required=True)
    p_info.add_argument("--output", required=True)

    p_backup = sub.add_parser("backup-db")
    p_backup.add_argument("--db", required=True)
    p_backup.add_argument("--dest", required=True)
    p_backup.add_argument("--output", required=True)

    p_pre = sub.add_parser("preflight")
    p_pre.add_argument("--app", required=True)
    p_pre.add_argument("--db", required=True)
    p_pre.add_argument("--data", required=True)
    p_pre.add_argument("--uploads", required=True)
    p_pre.add_argument("--output", required=True)

    args = parser.parse_args()
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if args.command == "db-info":
            result = user_snapshot(args.db)
        elif args.command == "backup-db":
            result = backup_db(args.db, args.dest)
        else:
            result = preflight(args.app, args.db, args.data, args.uploads)
        out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return 0
    except Exception as exc:
        result = {
            "ok": False,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
        try:
            out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
