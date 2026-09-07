from __future__ import annotations

import hashlib
import json
import math
import os
import re
import secrets
import shutil
import sqlite3
import time
import threading
import uuid
import socket
import subprocess
import ipaddress
import urllib.request
import urllib.error
import html as html_lib
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from urllib.parse import urlparse, quote

try:
    from bs4 import BeautifulSoup
except Exception:
    BeautifulSoup = None
try:
    from PIL import Image, ImageOps
except Exception:
    Image = None
    ImageOps = None
try:
    import pytesseract
except Exception:
    pytesseract = None

from flask import (
    Flask, abort, g, jsonify, request, send_from_directory, session
)
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

from ai_recipe import (
    generate_recipe as ai_generate_recipe,
    ollama_status as ai_ollama_status,
    parse_ai_json,
    normalize_ollama_url,
)

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("COOKBOOK_DATA_DIR", ROOT / "data"))
UPLOAD_DIR = Path(os.environ.get("COOKBOOK_UPLOAD_DIR", ROOT / "uploads"))
DB_PATH = Path(os.environ.get("COOKBOOK_DB_PATH", DATA_DIR / "cookbook.db"))
SEED_PATH = DATA_DIR / "seed_recipes.json"
CONFIG_PATH = ROOT / "config.json"

DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

def load_config():
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    cfg = {
        "secret_key": secrets.token_hex(32),
        "port": 3000,
        "site_name": "Family Cookbook",
        "allow_lan": True,
    }
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return cfg

CONFIG = load_config()

app = Flask(__name__, static_folder="static", static_url_path="")
app.secret_key = os.environ.get("COOKBOOK_SECRET_KEY", CONFIG["secret_key"])
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    MAX_CONTENT_LENGTH=100 * 1024 * 1024,
)
# Respect HTTPS information from Cloudflare/Tailscale reverse proxies.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

LOGIN_ATTEMPTS: dict[str, list[float]] = {}
AI_ATTEMPTS: dict[int, list[float]] = {}
AI_GENERATION_LOCK = threading.Lock()
ALLOWED_IMAGES = {"png", "jpg", "jpeg", "webp"}
ALLOWED_STORY_VIDEOS = {"mp4", "mov", "m4v", "webm"}
MAX_STORY_IMAGE_BYTES = 15 * 1024 * 1024
MAX_STORY_VIDEO_BYTES = 75 * 1024 * 1024
APP_VERSION = "3.3.0-beta.4"
SCHEMA_VERSION = 3

def utcnow():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

def db():
    if "db" not in g:
        conn = sqlite3.connect(DB_PATH, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=15000")
        g.db = conn
    return g.db

@app.teardown_appcontext
def close_db(_exc=None):
    conn = g.pop("db", None)
    if conn:
        conn.close()

def execute(sql, params=()):
    cur = db().execute(sql, params)
    db().commit()
    return cur

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS schema_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    INSERT OR IGNORE INTO schema_meta(key,value) VALUES('schema_version','1');

    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE COLLATE NOCASE,
        display_name TEXT NOT NULL,
        email TEXT,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('admin','member','guest')),
        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        last_login_at TEXT
    );

    CREATE TABLE IF NOT EXISTS invites (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code_hash TEXT NOT NULL UNIQUE,
        created_by INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        role TEXT NOT NULL CHECK(role IN ('member','guest')),
        label TEXT,
        expires_at TEXT,
        max_uses INTEGER NOT NULL DEFAULT 1,
        uses INTEGER NOT NULL DEFAULT 0,
        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS recipes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT,
        category TEXT NOT NULL DEFAULT 'Uncategorized',
        subcategory TEXT,
        equipment TEXT,
        servings_base REAL,
        servings_label TEXT,
        prep_text TEXT,
        cook_text TEXT,
        total_text TEXT,
        instructions TEXT,
        notes TEXT,
        tags TEXT,
        source_url TEXT,
        cover_image TEXT,
        owner_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
        legacy_contributor TEXT,
        status TEXT NOT NULL DEFAULT 'shared' CHECK(status IN ('shared','pending','draft','archived')),
        visibility TEXT NOT NULL DEFAULT 'family' CHECK(visibility IN ('family','private')),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS recipe_ingredients (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
        sort_order INTEGER NOT NULL DEFAULT 0,
        quantity_num REAL,
        quantity_text TEXT,
        unit TEXT,
        ingredient TEXT NOT NULL,
        ingredient_key TEXT NOT NULL,
        note TEXT,
        aisle TEXT,
        optional INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_ingredients_recipe ON recipe_ingredients(recipe_id);
    CREATE INDEX IF NOT EXISTS idx_ingredients_key ON recipe_ingredients(ingredient_key);

    CREATE TABLE IF NOT EXISTS ratings (
        recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
        updated_at TEXT NOT NULL,
        PRIMARY KEY(recipe_id,user_id)
    );

    CREATE TABLE IF NOT EXISTS comments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        body TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS favorites (
        recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        created_at TEXT NOT NULL,
        PRIMARY KEY(recipe_id,user_id)
    );

    CREATE TABLE IF NOT EXISTS cook_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        cooked_at TEXT NOT NULL,
        note TEXT
    );

    CREATE TABLE IF NOT EXISTS shopping_lists (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        shared INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS shopping_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        list_id INTEGER NOT NULL REFERENCES shopping_lists(id) ON DELETE CASCADE,
        display_name TEXT NOT NULL,
        ingredient_key TEXT,
        quantity_num REAL,
        quantity_text TEXT,
        unit TEXT,
        aisle TEXT,
        checked INTEGER NOT NULL DEFAULT 0,
        source_recipe_id INTEGER REFERENCES recipes(id) ON DELETE SET NULL,
        added_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS collections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        shared INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS collection_recipes (
        collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
        recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
        PRIMARY KEY(collection_id, recipe_id)
    );
    """)
    conn.commit()
    migrate_schema(conn)

    count = conn.execute("SELECT COUNT(*) FROM recipes").fetchone()[0]
    if count == 0 and SEED_PATH.exists():
        seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
        for r in seed:
            servings_base = parse_servings(r.get("servings"))
            cur = conn.execute("""
                INSERT INTO recipes
                (title,category,subcategory,equipment,servings_base,servings_label,
                 prep_text,cook_text,total_text,instructions,notes,tags,source_url,
                 legacy_contributor,status,visibility,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                r.get("title","Untitled"), r.get("category") or "Uncategorized",
                r.get("subcategory"), r.get("equipment"), servings_base,
                r.get("servings"), r.get("prep"), r.get("cook"), r.get("total"),
                r.get("instructions"), r.get("notes"), r.get("tags"),
                r.get("sourceUrl"), r.get("submittedBy") or "Travis",
                "shared", "family", utcnow(), utcnow()
            ))
            rid = cur.lastrowid
            for i, segment in enumerate(split_legacy_ingredients(r.get("ingredients",""))):
                parsed = parse_ingredient_segment(segment)
                conn.execute("""
                    INSERT INTO recipe_ingredients
                    (recipe_id,sort_order,quantity_num,quantity_text,unit,ingredient,
                     ingredient_key,note,aisle,optional)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                """, (
                    rid, i, parsed["quantity_num"], parsed["quantity_text"],
                    parsed["unit"], parsed["ingredient"],
                    normalize_ingredient(parsed["ingredient"]), "", guess_aisle(parsed["ingredient"]),
                    1 if "optional" in segment.lower() else 0
                ))
        conn.commit()
        migrate_categories(conn)
        migrate_legacy_recipe_steps(conn)
        conn.commit()
    conn.close()

UNICODE_FRACTIONS = {
    "¼": 0.25, "½": 0.5, "¾": 0.75, "⅓": 1/3, "⅔": 2/3,
    "⅛": 0.125, "⅜": 0.375, "⅝": 0.625, "⅞": 0.875
}
UNITS = {
    "tsp","tbsp","cup","cups","oz","ounce","ounces","lb","lbs","pound","pounds",
    "g","kg","ml","l","clove","cloves","can","cans","package","packages","pinch",
    "dash","dashes","shot","shots"
}

def parse_servings(v):
    if not v:
        return None
    m = re.match(r"\s*(\d+(?:\.\d+)?)\s*$", str(v))
    return float(m.group(1)) if m else None

def split_legacy_ingredients(text):
    if not text:
        return []
    # Existing cookbook data primarily uses semicolons.
    return [x.strip() for x in re.split(r";\s*", text) if x.strip()]

def parse_number_token(token):
    token = token.strip()
    if token in UNICODE_FRACTIONS:
        return UNICODE_FRACTIONS[token]
    m = re.match(r"^(\d+)([¼½¾⅓⅔⅛⅜⅝⅞])$", token)
    if m:
        return float(m.group(1)) + UNICODE_FRACTIONS[m.group(2)]
    m = re.match(r"^(\d+)\s+(\d+)/(\d+)$", token)
    if m:
        return float(m.group(1)) + float(m.group(2))/float(m.group(3))
    m = re.match(r"^(\d+)/(\d+)$", token)
    if m:
        return float(m.group(1))/float(m.group(2))
    try:
        return float(token)
    except Exception:
        return None

def parse_ingredient_segment(segment):
    original = segment.strip()
    # Remove labels like "Sauce:" but keep the following ingredient.
    segment = re.sub(r"^[A-Za-z][A-Za-z /&-]{0,25}:\s*", "", original).strip()
    words = segment.split()
    quantity_num = None
    quantity_text = ""
    unit = ""
    consumed = 0
    if words:
        # Try first token, then mixed number across two tokens.
        if len(words) >= 2 and re.match(r"^\d+$", words[0]) and re.match(r"^\d+/\d+$", words[1]):
            quantity_text = words[0] + " " + words[1]
            quantity_num = parse_number_token(quantity_text)
            consumed = 2
        elif not re.search(r"[-–]", words[0]):
            q = parse_number_token(words[0])
            if q is not None:
                quantity_num = q
                quantity_text = words[0]
                consumed = 1
        else:
            quantity_text = words[0]
            consumed = 1
        if consumed and len(words) > consumed and words[consumed].lower().rstrip(".,") in UNITS:
            unit = words[consumed].lower().rstrip(".,")
            consumed += 1
    ingredient = " ".join(words[consumed:]).strip(" ,") if consumed else segment
    if not ingredient:
        ingredient = original
    return {
        "quantity_num": quantity_num,
        "quantity_text": quantity_text,
        "unit": unit,
        "ingredient": ingredient
    }

def normalize_ingredient(text):
    t = re.sub(r"\([^)]*\)", " ", (text or "").lower())
    t = re.sub(r"\b(optional|divided|to taste|for serving|as needed|finely|roughly|fresh|dried|chopped|diced|minced|sliced|grated|shredded)\b", " ", t)
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()

def guess_aisle(name):
    n = normalize_ingredient(name)
    mapping = [
        ("Produce", ["onion","garlic","lime","lemon","pepper","carrot","cilantro","ginger","avocado","cucumber","cabbage","herb","spinach","potato","tomato"]),
        ("Meat & Seafood", ["chicken","beef","pork","sausage","tuna","salmon","fish","shrimp","turkey","steak"]),
        ("Dairy & Eggs", ["milk","cream","butter","cheese","parmesan","mascarpone","egg","yogurt"]),
        ("Bakery", ["bread","biscuit","tortilla","ladyfinger"]),
        ("Frozen", ["ice cream","frozen"]),
        ("Pantry", ["rice","pasta","flour","sugar","broth","stock","oil","sauce","beans","coconut milk","spice","cumin","paprika","oregano","thyme","rosemary","vanilla","cocoa","coffee","espresso"]),
    ]
    for aisle, keys in mapping:
        if any(k in n for k in keys):
            return aisle
    return "Other"


def table_columns(conn, table):
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}

def ensure_column(conn, table, column, definition):
    if column not in table_columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

def setting_get_conn(conn, key, default=None):
    row = conn.execute("SELECT value FROM site_settings WHERE key=?", (key,)).fetchone()
    return row[0] if row else default

def setting_get(key, default=None):
    row = db().execute("SELECT value FROM site_settings WHERE key=?", (key,)).fetchone()
    return row[0] if row else default

def setting_set(key, value):
    execute("INSERT INTO site_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))

def migrate_schema(conn):
    # Additive migrations only. Existing users, passwords, recipes and history are never recreated.
    conn.execute("CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("INSERT OR IGNORE INTO schema_meta(key,value) VALUES('schema_version','1')")

    ensure_column(conn, 'users', 'avatar_path', 'TEXT')
    ensure_column(conn, 'users', 'theme_pref', "TEXT NOT NULL DEFAULT 'system'")

    for col, definition in [
        ('original_author','TEXT'),('approx_year','TEXT'),('family_branch','TEXT'),('occasion','TEXT'),
        ('family_story','TEXT'),('cuisine','TEXT'),('quality_status',"TEXT NOT NULL DEFAULT 'needs_review'"),
        ('parent_recipe_id','INTEGER REFERENCES recipes(id) ON DELETE SET NULL')
    ]:
        ensure_column(conn, 'recipes', col, definition)
    ensure_column(conn, 'recipe_ingredients', 'prep_note', 'TEXT')
    ensure_column(conn, 'recipe_ingredients', 'scalable', 'INTEGER NOT NULL DEFAULT 1')

    conn.executescript("""
    CREATE TABLE IF NOT EXISTS recipe_steps (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
        step_number INTEGER NOT NULL,
        title TEXT,
        instruction TEXT NOT NULL,
        temp_f REAL,
        duration_minutes REAL,
        timer_label TEXT,
        doneness TEXT,
        UNIQUE(recipe_id, step_number)
    );
    CREATE TABLE IF NOT EXISTS recipe_step_ingredients (
        step_id INTEGER NOT NULL REFERENCES recipe_steps(id) ON DELETE CASCADE,
        ingredient_id INTEGER NOT NULL REFERENCES recipe_ingredients(id) ON DELETE CASCADE,
        quantity_fraction REAL NOT NULL DEFAULT 1,
        note TEXT,
        PRIMARY KEY(step_id, ingredient_id)
    );
    CREATE TABLE IF NOT EXISTS recipe_sources (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
        source_type TEXT NOT NULL,
        source_url TEXT,
        source_label TEXT,
        source_text TEXT,
        file_path TEXT,
        created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS recipe_pairings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
        paired_recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
        pairing_type TEXT NOT NULL,
        note TEXT,
        created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
        created_at TEXT NOT NULL,
        UNIQUE(recipe_id, paired_recipe_id, pairing_type)
    );
    CREATE TABLE IF NOT EXISTS personal_recipe_notes (
        recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        body TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY(recipe_id,user_id)
    );
    CREATE TABLE IF NOT EXISTS recipe_revisions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
        changed_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
        snapshot_json TEXT NOT NULL,
        reason TEXT,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS import_staging (
        token TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        source_type TEXT NOT NULL,
        source_url TEXT,
        source_label TEXT,
        source_text TEXT,
        source_files_json TEXT,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS site_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """)
    defaults = {
        'site_name':'Table & Tale',
        'tagline':'Recipes worth remembering.',
        'brand_accent':'#b85f3f',
        'public_url':'',
        'ai_enabled':'0',
        'ai_ollama_url':'http://127.0.0.1:11434',
        'ai_text_model':'qwen3:8b',
        'ai_timeout_seconds':'180'
    }
    for k,v in defaults.items():
        conn.execute("INSERT OR IGNORE INTO site_settings(key,value) VALUES(?,?)", (k,v))
    migrate_categories(conn)
    migrate_legacy_recipe_steps(conn)
    conn.execute("INSERT INTO schema_meta(key,value) VALUES('schema_version',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(SCHEMA_VERSION),))
    conn.commit()

def migrate_categories(conn):
    if 'recipes' not in {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}:
        return
    conn.execute("UPDATE recipes SET category='Main Dishes' WHERE category='Dinner & Savory'")
    conn.execute("UPDATE recipes SET category='Drinks' WHERE category='Coffee & Drinks'")
    conn.execute("UPDATE recipes SET category='Breakfast & Brunch' WHERE category='Breakfast & Sides' AND lower(coalesce(subcategory,'')) LIKE '%breakfast%'")
    conn.execute("UPDATE recipes SET category='Sides' WHERE category='Breakfast & Sides'")
    conn.execute("UPDATE recipes SET category='Desserts' WHERE category='Frozen & Dessert'")
    conn.execute("UPDATE recipes SET category='Drinks' WHERE category='Desserts' AND (lower(coalesce(subcategory,'')) LIKE '%milkshake%' OR lower(coalesce(subcategory,'')) LIKE '%frozen coffee%')")

def split_instruction_steps(text):
    t = (text or '').strip()
    if not t:
        return []
    lines = [re.sub(r'^\s*(?:step\s*)?\d+[\).:-]?\s*', '', x.strip(), flags=re.I) for x in t.splitlines() if x.strip()]
    if len(lines) >= 2:
        return lines
    parts = re.split(r'(?<=[.!?])\s+(?=[A-Z])', t)
    parts = [p.strip() for p in parts if p.strip()]
    return parts if len(parts) > 1 else [t]

def significant_terms(ingredient_key):
    stop = {'fresh','dried','whole','large','small','medium','optional','shredded','grated','diced','minced','sliced','chopped','boneless','skinless'}
    return [w for w in (ingredient_key or '').split() if len(w) >= 4 and w not in stop]

def ingredient_mentioned(step_text, ingredient_key):
    step=normalize_ingredient(step_text or '')
    key=normalize_ingredient(ingredient_key or '')
    if key and len(key)>=4 and key in step:
        return True
    terms=significant_terms(key)
    return bool(terms and all(t in step for t in terms[:2]))

def migrate_legacy_recipe_steps(conn):
    rows = conn.execute("SELECT id,instructions FROM recipes WHERE coalesce(instructions,'')<>'' AND NOT EXISTS (SELECT 1 FROM recipe_steps s WHERE s.recipe_id=recipes.id)").fetchall()
    for rid, instructions in rows:
        steps = split_instruction_steps(instructions)
        step_ids=[]
        for n, st in enumerate(steps,1):
            temp = extract_temp_f(st)
            dur = extract_duration_minutes(st)
            cur = conn.execute("INSERT INTO recipe_steps(recipe_id,step_number,instruction,temp_f,duration_minutes) VALUES(?,?,?,?,?)", (rid,n,st,temp,dur))
            step_ids.append(cur.lastrowid)
        ingredients = conn.execute("SELECT id,ingredient_key FROM recipe_ingredients WHERE recipe_id=?", (rid,)).fetchall()
        norm_steps=[normalize_ingredient(s) for s in steps]
        # Link only ingredients that appear in exactly one step. Ambiguous split quantities stay unlinked until review.
        for iid, key in ingredients:
            terms=significant_terms(key)
            if not terms: continue
            hits=[i for i,s in enumerate(norm_steps) if ingredient_mentioned(s,key)]
            if len(hits)==1:
                conn.execute("INSERT OR IGNORE INTO recipe_step_ingredients(step_id,ingredient_id,quantity_fraction) VALUES(?,?,1)", (step_ids[hits[0]],iid))

def extract_temp_f(text):
    m=re.search(r'\b(\d{3})\s*(?:°|degrees?\s*)?f\b', text or '', re.I)
    return float(m.group(1)) if m else None

def extract_duration_minutes(text):
    m=re.search(r'\b(\d+(?:\.\d+)?)\s*(?:-|to)?\s*(\d+(?:\.\d+)?)?\s*(minutes?|mins?|hours?|hrs?)\b', text or '', re.I)
    if not m: return None
    a=float(m.group(1)); b=float(m.group(2)) if m.group(2) else a
    val=(a+b)/2
    return val*60 if m.group(3).lower().startswith(('hour','hr')) else val

def branding_json():
    return {
        'site_name':setting_get('site_name','Table & Tale'),
        'tagline':setting_get('tagline','Recipes worth remembering.'),
        'brand_accent':setting_get('brand_accent','#b85f3f')
    }

def normalize_public_url(value):
    value=(value or '').strip().rstrip('/')
    if not value:
        return ''
    parsed=urlparse(value)
    if parsed.scheme.lower()!='https' or not parsed.netloc:
        raise ValueError('Public cookbook URL must be a full HTTPS address')
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Public cookbook URL must be a simple HTTPS address without credentials, query parameters, or fragments')
    if parsed.path not in {'','/'}:
        raise ValueError('Public cookbook URL should be the cookbook root, for example https://cookbook.example.com')
    return f"https://{parsed.netloc}"

def _tailscale_cli_candidates():
    found=shutil.which('tailscale')
    if found:
        yield found
    pf=os.environ.get('ProgramFiles')
    if pf:
        candidate=str(Path(pf)/'Tailscale'/'tailscale.exe')
        if Path(candidate).exists():
            yield candidate

def detect_tailscale_funnel_url():
    """Best-effort discovery. A manually configured public URL always wins."""
    seen=set()
    for cli in _tailscale_cli_candidates():
        if cli in seen:
            continue
        seen.add(cli)
        try:
            kwargs=dict(capture_output=True,text=True,timeout=4,check=False)
            if os.name=='nt' and hasattr(subprocess,'CREATE_NO_WINDOW'):
                kwargs['creationflags']=subprocess.CREATE_NO_WINDOW
            proc=subprocess.run([cli,'funnel','status'],**kwargs)
            text=(proc.stdout or '')+'\n'+(proc.stderr or '')
            matches=re.findall(r'https://[A-Za-z0-9.-]+\.ts\.net(?::\d+)?',text,re.I)
            if matches:
                return matches[0].rstrip('/')
        except Exception:
            continue
    return ''

def request_public_origin():
    try:
        parsed=urlparse(request.url_root)
        host=(parsed.hostname or '').lower()
        if parsed.scheme!='https' or not host or host=='localhost':
            return ''
        try:
            ip=ipaddress.ip_address(host)
            if ip.is_private or ip.is_loopback or ip.is_link_local:
                return ''
        except ValueError:
            pass
        return f"https://{parsed.netloc}".rstrip('/')
    except Exception:
        return ''

def sharing_json():
    configured=(setting_get('public_url','') or '').strip().rstrip('/')
    detected=detect_tailscale_funnel_url() if not configured else ''
    effective=configured or request_public_origin() or detected
    source='configured' if configured else ('current_public_address' if request_public_origin() else ('tailscale_funnel' if detected else 'none'))
    return {
        'public_url':configured,
        'detected_public_url':detected,
        'effective_public_url':effective,
        'source':source
    }

def effective_invite_base_url():
    sharing=sharing_json()
    if sharing['effective_public_url']:
        return sharing['effective_public_url'], sharing['source'], True
    return request.url_root.rstrip('/'), 'current_address', False

def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    return db().execute("SELECT * FROM users WHERE id=? AND active=1", (uid,)).fetchone()

def user_json(row):
    return {
        "id": row["id"], "username": row["username"], "display_name": row["display_name"],
        "email": row["email"], "role": row["role"], "created_at": row["created_at"],
        "avatar_path": row["avatar_path"] if "avatar_path" in row.keys() else None,
        "theme_pref": row["theme_pref"] if "theme_pref" in row.keys() else "system"
    }

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        u = current_user()
        if not u:
            return jsonify(error="Authentication required"), 401
        g.user = u
        return fn(*args, **kwargs)
    return wrapper

def admin_required(fn):
    @wraps(fn)
    @login_required
    def wrapper(*args, **kwargs):
        if g.user["role"] != "admin":
            return jsonify(error="Admin access required"), 403
        return fn(*args, **kwargs)
    return wrapper

def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(24)
    return session["csrf"]

@app.before_request
def csrf_and_security():
    # CSRF protect every state-changing API route, including login/setup/register.
    if request.path.startswith("/api/") and request.method in {"POST","PUT","PATCH","DELETE"}:
        supplied = request.headers.get("X-CSRF-Token", "")
        if not supplied or not secrets.compare_digest(supplied, session.get("csrf","")):
            return jsonify(error="Invalid or missing CSRF token"), 403

@app.after_request
def security_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "same-origin"
    resp.headers["Permissions-Policy"] = "camera=(self), microphone=(), geolocation=(), screen-wake-lock=(self)"
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data: blob:; "
        "style-src 'self' 'unsafe-inline'; script-src 'self'; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    )
    # Keep the app shell fresh across self-hosted upgrades. The service worker
    # script must never be allowed to linger in the HTTP cache.
    if request.path == "/sw.js":
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        resp.headers["Service-Worker-Allowed"] = "/"
    elif request.path == "/" or request.path.endswith(".html"):
        resp.headers["Cache-Control"] = "no-cache, must-revalidate"
    if request.is_secure:
        resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return resp

def too_many_login_attempts(key):
    now = time.time()
    attempts = [t for t in LOGIN_ATTEMPTS.get(key, []) if now - t < 900]
    LOGIN_ATTEMPTS[key] = attempts
    return len(attempts) >= 8

def record_login_failure(key):
    LOGIN_ATTEMPTS.setdefault(key, []).append(time.time())

def clear_login_failures(key):
    LOGIN_ATTEMPTS.pop(key, None)

def invite_hash(code):
    return hashlib.sha256(code.strip().encode("utf-8")).hexdigest()

def can_edit_recipe(user, recipe):
    return user["role"] == "admin" or recipe["owner_id"] == user["id"]

def row_to_recipe(row, include_ingredients=False):
    item = dict(row)
    item["is_favorite"] = bool(item.get("is_favorite", 0))
    item["rating_avg"] = round(item.get("rating_avg") or 0, 2)
    item["rating_count"] = item.get("rating_count") or 0
    item["made_count"] = item.get("made_count") or 0
    if include_ingredients:
        item["ingredients"] = [dict(r) for r in db().execute(
            "SELECT * FROM recipe_ingredients WHERE recipe_id=? ORDER BY sort_order,id", (row["id"],)
        ).fetchall()]
    return item

# ---------- Status/Auth ----------

@app.get("/api/status")
def api_status():
    count = db().execute("SELECT COUNT(*) FROM users").fetchone()[0]
    u = current_user()
    return jsonify(
        setup_required=(count == 0),
        user=user_json(u) if u else None,
        csrf=csrf_token(),
        branding=branding_json(),
        app_version=APP_VERSION
    )

@app.post("/api/setup")
def api_setup():
    if db().execute("SELECT COUNT(*) FROM users").fetchone()[0] != 0:
        return jsonify(error="Setup is already complete"), 409
    body = request.get_json(silent=True) or {}
    username = (body.get("username") or "").strip()
    display = (body.get("display_name") or "").strip()
    password = body.get("password") or ""
    if len(username) < 3 or len(display) < 1 or len(password) < 10:
        return jsonify(error="Use a username of 3+ characters and a password of at least 10 characters"), 400
    cur = execute(
        "INSERT INTO users(username,display_name,email,password_hash,role,created_at) VALUES(?,?,?,?,?,?)",
        (username, display, (body.get("email") or "").strip() or None,
         generate_password_hash(password), "admin", utcnow())
    )
    uid = cur.lastrowid
    # Attribute imported Travis recipes to the first admin.
    execute("UPDATE recipes SET owner_id=? WHERE owner_id IS NULL AND lower(coalesce(legacy_contributor,''))='travis'", (uid,))
    execute("INSERT INTO shopping_lists(name,owner_id,shared,created_at) VALUES(?,?,1,?)", ("Family Grocery List", uid, utcnow()))
    session.clear()
    session["user_id"] = uid
    csrf_token()
    return jsonify(ok=True, user=user_json(db().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()))

@app.post("/api/login")
def api_login():
    body = request.get_json(silent=True) or {}
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    key = f"{request.remote_addr}:{username.lower()}"
    if too_many_login_attempts(key):
        return jsonify(error="Too many login attempts. Try again later."), 429
    u = db().execute("SELECT * FROM users WHERE username=? COLLATE NOCASE AND active=1", (username,)).fetchone()
    if not u or not check_password_hash(u["password_hash"], password):
        record_login_failure(key)
        return jsonify(error="Invalid username or password"), 401
    clear_login_failures(key)
    session.clear()
    session["user_id"] = u["id"]
    csrf_token()
    execute("UPDATE users SET last_login_at=? WHERE id=?", (utcnow(), u["id"]))
    return jsonify(ok=True, user=user_json(u))

@app.post("/api/logout")
def api_logout():
    session.clear()
    csrf_token()
    return jsonify(ok=True)

@app.post("/api/register")
def api_register():
    body = request.get_json(silent=True) or {}
    code = (body.get("invite_code") or "").strip()
    username = (body.get("username") or "").strip()
    display = (body.get("display_name") or "").strip()
    password = body.get("password") or ""
    if len(username) < 3 or len(display) < 1 or len(password) < 10:
        return jsonify(error="Username must be 3+ characters and password must be at least 10 characters"), 400
    inv = db().execute("SELECT * FROM invites WHERE code_hash=?", (invite_hash(code),)).fetchone()
    if not inv or not inv["active"] or inv["uses"] >= inv["max_uses"]:
        return jsonify(error="That invite is invalid or has already been used"), 400
    if inv["expires_at"] and inv["expires_at"] < utcnow():
        return jsonify(error="That invite has expired"), 400
    try:
        cur = execute(
            "INSERT INTO users(username,display_name,email,password_hash,role,created_at) VALUES(?,?,?,?,?,?)",
            (username, display, (body.get("email") or "").strip() or None,
             generate_password_hash(password), inv["role"], utcnow())
        )
    except sqlite3.IntegrityError:
        return jsonify(error="That username is already taken"), 409
    execute("UPDATE invites SET uses=uses+1 WHERE id=?", (inv["id"],))
    session.clear()
    session["user_id"] = cur.lastrowid
    csrf_token()
    u = db().execute("SELECT * FROM users WHERE id=?", (cur.lastrowid,)).fetchone()
    return jsonify(ok=True, user=user_json(u))

@app.post("/api/change-password")
@login_required
def change_password():
    body = request.get_json(silent=True) or {}
    current = body.get("current_password") or ""
    new = body.get("new_password") or ""
    if not check_password_hash(g.user["password_hash"], current):
        return jsonify(error="Current password is incorrect"), 400
    if len(new) < 10:
        return jsonify(error="New password must be at least 10 characters"), 400
    execute("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(new), g.user["id"]))
    return jsonify(ok=True)

# ---------- Admin / family ----------

@app.get("/api/users")
@login_required
def api_users():
    rows = db().execute("""
        SELECT u.id,u.username,u.display_name,u.email,u.role,u.created_at,u.active,u.avatar_path,u.theme_pref,
               COUNT(DISTINCT r.id) recipe_count,
               COUNT(DISTINCT c.id) comment_count
        FROM users u
        LEFT JOIN recipes r ON r.owner_id=u.id AND r.status='shared'
        LEFT JOIN comments c ON c.user_id=u.id
        WHERE u.active=1
        GROUP BY u.id ORDER BY u.display_name COLLATE NOCASE
    """).fetchall()
    return jsonify([dict(r) for r in rows])

@app.get("/api/profile")
@login_required
def api_profile():
    uid = request.args.get("user_id", type=int) or g.user["id"]
    u = db().execute("SELECT id,username,display_name,email,role,created_at,active,avatar_path,theme_pref FROM users WHERE id=? AND active=1", (uid,)).fetchone()
    if not u:
        return jsonify(error="User not found"), 404
    stats = db().execute("""
        SELECT
          (SELECT COUNT(*) FROM recipes WHERE owner_id=? AND status='shared') recipes,
          (SELECT COUNT(*) FROM ratings WHERE user_id=?) ratings,
          (SELECT COUNT(*) FROM comments WHERE user_id=?) comments,
          (SELECT COUNT(*) FROM cook_events WHERE user_id=?) made_count
    """, (uid,uid,uid,uid)).fetchone()
    recent = db().execute("""
        SELECT id,title,category,created_at FROM recipes
        WHERE owner_id=? AND status='shared'
        ORDER BY created_at DESC LIMIT 12
    """, (uid,)).fetchall()
    return jsonify(user=dict(u), stats=dict(stats), recipes=[dict(x) for x in recent])

@app.post("/api/admin/invites")
@admin_required
def create_invite():
    body = request.get_json(silent=True) or {}
    role = body.get("role","member")
    if role not in {"member","guest"}:
        return jsonify(error="Role must be member or guest"), 400
    days = max(1, min(int(body.get("days", 14)), 90))
    max_uses = max(1, min(int(body.get("max_uses", 1)), 25))
    code = secrets.token_urlsafe(18)
    expires = (datetime.now(timezone.utc) + timedelta(days=days)).replace(microsecond=0).isoformat()
    execute("""
        INSERT INTO invites(code_hash,created_by,role,label,expires_at,max_uses,created_at)
        VALUES(?,?,?,?,?,?,?)
    """, (invite_hash(code), g.user["id"], role, (body.get("label") or "").strip() or None, expires, max_uses, utcnow()))
    base_url, url_source, is_public = effective_invite_base_url()
    invite_url=f"{base_url}/?invite={quote(code, safe='')}"
    return jsonify(ok=True, code=code, expires_at=expires, role=role, max_uses=max_uses,
                   invite_url=invite_url, url_source=url_source, public_url=is_public)

@app.get("/api/admin/invites")
@admin_required
def list_invites():
    rows = db().execute("""
        SELECT i.id,i.role,i.label,i.expires_at,i.max_uses,i.uses,i.active,i.created_at,u.display_name created_by_name
        FROM invites i JOIN users u ON u.id=i.created_by ORDER BY i.created_at DESC
    """).fetchall()
    return jsonify([dict(r) for r in rows])


@app.post("/api/admin/users/<int:uid>/reset-password")
@admin_required
def admin_reset_password(uid):
    if uid == g.user["id"]:
        return jsonify(error="Use Change Password for your own account"), 400
    body = request.get_json(silent=True) or {}
    new = body.get("new_password") or ""
    if len(new) < 10:
        return jsonify(error="Temporary password must be at least 10 characters"), 400
    target = db().execute("SELECT id FROM users WHERE id=? AND active=1", (uid,)).fetchone()
    if not target:
        return jsonify(error="User not found"), 404
    execute("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(new), uid))
    return jsonify(ok=True)

@app.patch("/api/admin/users/<int:uid>")
@admin_required
def admin_update_user(uid):
    if uid == g.user["id"]:
        return jsonify(error="Use your profile settings for your own account"), 400
    body = request.get_json(silent=True) or {}
    role = body.get("role")
    active = body.get("active")
    if role and role not in {"member","guest","admin"}:
        return jsonify(error="Invalid role"), 400
    if role:
        execute("UPDATE users SET role=? WHERE id=?", (role,uid))
    if active is not None:
        execute("UPDATE users SET active=? WHERE id=?", (1 if active else 0,uid))
    return jsonify(ok=True)


# ---------- Profile / branding ----------

@app.patch("/api/me/preferences")
@login_required
def update_preferences():
    body=request.get_json(silent=True) or {}
    theme=body.get('theme_pref')
    if theme is not None:
        if theme not in {'system','light','dark'}:
            return jsonify(error='Invalid theme'),400
        execute("UPDATE users SET theme_pref=? WHERE id=?", (theme,g.user['id']))
    return jsonify(ok=True,user=user_json(db().execute("SELECT * FROM users WHERE id=?",(g.user['id'],)).fetchone()))

@app.post("/api/me/avatar")
@login_required
def upload_avatar():
    f=request.files.get('image')
    if not f or not f.filename or '.' not in f.filename:
        return jsonify(error='Choose a profile image'),400
    ext=f.filename.rsplit('.',1)[1].lower()
    if ext not in ALLOWED_IMAGES or Image is None:
        return jsonify(error='Use PNG, JPG, JPEG, or WEBP'),400
    folder=UPLOAD_DIR/'avatars';folder.mkdir(parents=True,exist_ok=True)
    dest=folder/f"user-{g.user['id']}.webp"
    try:
        im=Image.open(f.stream).convert('RGB')
        size=min(im.width,im.height); left=(im.width-size)//2; top=(im.height-size)//2
        im=im.crop((left,top,left+size,top+size)).resize((320,320))
        im.save(dest,'WEBP',quality=86,method=6)
    except Exception as e:
        return jsonify(error=f'Could not process image: {e}'),400
    rel=str(dest.relative_to(UPLOAD_DIR)).replace('\\','/')
    execute("UPDATE users SET avatar_path=? WHERE id=?",(rel,g.user['id']))
    return jsonify(ok=True,avatar_path=rel)

def ai_settings_json():
    try:
        timeout=max(30,min(600,int(setting_get('ai_timeout_seconds','180') or 180)))
    except Exception:
        timeout=180
    return {
        'enabled': setting_get('ai_enabled','0')=='1',
        'ollama_url': setting_get('ai_ollama_url','http://127.0.0.1:11434'),
        'text_model': setting_get('ai_text_model','qwen3:8b'),
        'timeout_seconds': timeout
    }

def too_many_ai_requests(uid):
    now=time.time()
    attempts=[t for t in AI_ATTEMPTS.get(uid,[]) if now-t<1800]
    AI_ATTEMPTS[uid]=attempts
    return len(attempts)>=12

def record_ai_request(uid):
    AI_ATTEMPTS.setdefault(uid,[]).append(time.time())

@app.get("/api/ai/status")
@login_required
def ai_status():
    cfg=ai_settings_json()
    if not cfg['enabled']:
        return jsonify(enabled=False,available=False,model=cfg['text_model'],message='Local AI is disabled by the family admin.')
    status=ai_ollama_status(cfg['ollama_url'],cfg['text_model'],timeout=3)
    return jsonify(enabled=True,model=cfg['text_model'],**status)


@app.get("/api/admin/settings")
@admin_required
def admin_settings_get():
    return jsonify(branding=branding_json(), sharing=sharing_json(), ai=ai_settings_json())

@app.post("/api/admin/settings")
@admin_required
def admin_settings_update():
    body=request.get_json(silent=True) or {}
    if 'site_name' in body and (body['site_name'] or '').strip(): setting_set('site_name',(body['site_name'] or '').strip()[:80])
    if 'tagline' in body: setting_set('tagline',(body['tagline'] or '').strip()[:160])
    if 'brand_accent' in body and re.match(r'^#[0-9a-fA-F]{6}$',body['brand_accent'] or ''): setting_set('brand_accent',body['brand_accent'])
    if 'public_url' in body:
        try:
            setting_set('public_url', normalize_public_url(body.get('public_url')))
        except ValueError as e:
            return jsonify(error=str(e)),400
    if 'ai_enabled' in body:
        setting_set('ai_enabled','1' if bool(body.get('ai_enabled')) else '0')
    if 'ai_ollama_url' in body:
        try:
            setting_set('ai_ollama_url',normalize_ollama_url(body.get('ai_ollama_url')))
        except ValueError as e:
            return jsonify(error=str(e)),400
    if 'ai_text_model' in body:
        model=(body.get('ai_text_model') or '').strip()
        if not re.fullmatch(r'[A-Za-z0-9_.:/-]{1,120}',model):
            return jsonify(error='Invalid Ollama model name'),400
        setting_set('ai_text_model',model)
    if 'ai_timeout_seconds' in body:
        try: timeout=max(30,min(600,int(body.get('ai_timeout_seconds'))))
        except Exception: return jsonify(error='AI timeout must be a number from 30 to 600 seconds'),400
        setting_set('ai_timeout_seconds',str(timeout))
    return jsonify(ok=True,branding=branding_json(),sharing=sharing_json(),ai=ai_settings_json())

# ---------- Recipe queries ----------

BASE_RECIPE_SELECT = """
SELECT r.*,
       u.display_name owner_name,
       u.avatar_path owner_avatar,
       COALESCE(AVG(rt.rating),0) rating_avg,
       COUNT(DISTINCT rt.user_id) rating_count,
       COUNT(DISTINCT ce.id) made_count,
       EXISTS(SELECT 1 FROM favorites f WHERE f.recipe_id=r.id AND f.user_id=?) is_favorite,
       (SELECT rating FROM ratings mine WHERE mine.recipe_id=r.id AND mine.user_id=?) my_rating
FROM recipes r
LEFT JOIN users u ON u.id=r.owner_id
LEFT JOIN ratings rt ON rt.recipe_id=r.id
LEFT JOIN cook_events ce ON ce.recipe_id=r.id
"""

@app.get("/api/recipes")
@login_required
def api_recipes():
    params = [g.user["id"], g.user["id"]]
    where = ["r.status='shared'", "(r.visibility='family' OR r.owner_id=?)"]
    params.append(g.user["id"])

    q = (request.args.get("q") or "").strip().lower()
    category = (request.args.get("category") or "").strip()
    owner = request.args.get("owner", type=int)
    include = [normalize_ingredient(x) for x in request.args.get("ingredients","").split(",") if normalize_ingredient(x)]
    exclude = [normalize_ingredient(x) for x in request.args.get("exclude","").split(",") if normalize_ingredient(x)]

    if q:
        where.append("""(
            lower(r.title) LIKE ? OR lower(coalesce(r.description,'')) LIKE ? OR
            lower(coalesce(r.category,'')) LIKE ? OR lower(coalesce(r.subcategory,'')) LIKE ? OR
            lower(coalesce(r.equipment,'')) LIKE ? OR lower(coalesce(r.tags,'')) LIKE ? OR
            lower(coalesce(r.notes,'')) LIKE ? OR EXISTS(
                SELECT 1 FROM recipe_ingredients qi
                WHERE qi.recipe_id=r.id AND lower(qi.ingredient) LIKE ?
            )
        )""")
        like = f"%{q}%"
        params.extend([like]*8)
    if category:
        where.append("r.category=?")
        params.append(category)
    if owner:
        where.append("r.owner_id=?")
        params.append(owner)
    for ing in include:
        where.append("EXISTS(SELECT 1 FROM recipe_ingredients ii WHERE ii.recipe_id=r.id AND ii.ingredient_key LIKE ?)")
        params.append(f"%{ing}%")
    for ing in exclude:
        where.append("NOT EXISTS(SELECT 1 FROM recipe_ingredients ei WHERE ei.recipe_id=r.id AND ei.ingredient_key LIKE ?)")
        params.append(f"%{ing}%")

    sql = BASE_RECIPE_SELECT + " WHERE " + " AND ".join(where) + " GROUP BY r.id "
    sort = request.args.get("sort","az")
    if sort == "rating":
        sql += " ORDER BY rating_avg DESC, rating_count DESC, r.title COLLATE NOCASE"
    elif sort == "newest":
        sql += " ORDER BY r.created_at DESC"
    elif sort == "made":
        sql += " ORDER BY made_count DESC, r.title COLLATE NOCASE"
    else:
        sql += " ORDER BY r.title COLLATE NOCASE"
    rows = db().execute(sql, params).fetchall()
    return jsonify([row_to_recipe(r) for r in rows])

@app.get("/api/recipes/<int:rid>")
@login_required
def recipe_detail(rid):
    row = db().execute(
        BASE_RECIPE_SELECT + " WHERE r.id=? AND r.status IN ('shared','pending','draft') GROUP BY r.id",
        (g.user["id"], g.user["id"], rid)
    ).fetchone()
    if not row:
        return jsonify(error="Recipe not found"), 404
    if row["visibility"] == "private" and row["owner_id"] != g.user["id"] and g.user["role"] != "admin":
        return jsonify(error="Recipe not found"), 404
    item = row_to_recipe(row, True)
    comments = db().execute("""
        SELECT c.id,c.body,c.created_at,c.updated_at,c.user_id,u.display_name,u.role,u.avatar_path
        FROM comments c JOIN users u ON u.id=c.user_id
        WHERE c.recipe_id=? ORDER BY c.created_at
    """, (rid,)).fetchall()
    item["comments"] = [dict(c) for c in comments]
    steps=[]
    for s in db().execute("SELECT * FROM recipe_steps WHERE recipe_id=? ORDER BY step_number,id",(rid,)).fetchall():
        sd=dict(s)
        sd['ingredients']=[dict(x) for x in db().execute("""
          SELECT si.quantity_fraction,si.note,i.id ingredient_id,i.quantity_num,i.quantity_text,i.unit,i.ingredient,i.prep_note,i.scalable
          FROM recipe_step_ingredients si JOIN recipe_ingredients i ON i.id=si.ingredient_id
          WHERE si.step_id=? ORDER BY i.sort_order,i.id
        """,(s['id'],)).fetchall()]
        steps.append(sd)
    item['steps']=steps
    item['sources']=[dict(x) for x in db().execute("SELECT id,source_type,source_url,source_label,source_text,file_path,created_at FROM recipe_sources WHERE recipe_id=? ORDER BY id",(rid,)).fetchall()]
    item['story_media']=[x for x in item['sources'] if (x.get('source_type') or '').startswith('story_')]
    note=db().execute("SELECT body FROM personal_recipe_notes WHERE recipe_id=? AND user_id=?",(rid,g.user['id'])).fetchone()
    item['my_note']=note['body'] if note else ''
    item['pairings']=get_pairings(rid)
    item['revisions']=[dict(x) for x in db().execute("""SELECT rv.id,rv.reason,rv.created_at,u.display_name changed_by_name FROM recipe_revisions rv LEFT JOIN users u ON u.id=rv.changed_by WHERE rv.recipe_id=? ORDER BY rv.id DESC LIMIT 20""",(rid,)).fetchall()]
    item['quality_warnings']=recipe_quality_warnings(item)
    return jsonify(item)

def normalize_recipe_payload(body):
    return {
        "title": (body.get("title") or "").strip(),
        "description": (body.get("description") or "").strip(),
        "category": (body.get("category") or "Uncategorized").strip(),
        "subcategory": (body.get("subcategory") or "").strip(),
        "equipment": (body.get("equipment") or "").strip(),
        "servings_base": float(body["servings_base"]) if str(body.get("servings_base","")).strip() else None,
        "servings_label": (body.get("servings_label") or "").strip(),
        "prep_text": (body.get("prep_text") or "").strip(),
        "cook_text": (body.get("cook_text") or "").strip(),
        "total_text": (body.get("total_text") or "").strip(),
        "instructions": (body.get("instructions") or "").strip(),
        "notes": (body.get("notes") or "").strip(),
        "tags": (body.get("tags") or "").strip(),
        "source_url": (body.get("source_url") or "").strip(),
        "visibility": body.get("visibility") if body.get("visibility") in {"family","private"} else "family",
        "ingredients": body.get("ingredients") or [],
        "steps": body.get("steps") or [],
        "original_author": (body.get("original_author") or "").strip(),
        "approx_year": (body.get("approx_year") or "").strip(),
        "family_branch": (body.get("family_branch") or "").strip(),
        "occasion": (body.get("occasion") or "").strip(),
        "family_story": (body.get("family_story") or "").strip(),
        "cuisine": (body.get("cuisine") or "").strip(),
        "parent_recipe_id": int(body["parent_recipe_id"]) if str(body.get("parent_recipe_id","")).isdigit() else None,
        "import_token": (body.get("import_token") or "").strip(),
    }

def replace_ingredients(rid, ingredients):
    execute("DELETE FROM recipe_ingredients WHERE recipe_id=?", (rid,))
    ids=[]
    for i, item in enumerate(ingredients):
        if isinstance(item, str):
            p = parse_ingredient_segment(item); name=p['ingredient']; qty_num=p['quantity_num']; qty_text=p['quantity_text']; unit=p['unit']; note=''; prep=''; aisle=guess_aisle(name); optional=0; scalable=1
        else:
            name=(item.get('ingredient') or '').strip()
            if not name: ids.append(None); continue
            qty_num=None; qty_text=(item.get('quantity_text') or '').strip()
            if str(item.get('quantity_num','')).strip():
                try: qty_num=float(item['quantity_num'])
                except: qty_num=None
            if qty_num is None and qty_text and not re.search(r'[-–]',qty_text): qty_num=parse_number_token(qty_text)
            unit=(item.get('unit') or '').strip(); note=(item.get('note') or '').strip(); prep=(item.get('prep_note') or '').strip(); aisle=(item.get('aisle') or guess_aisle(name)).strip(); optional=1 if item.get('optional') else 0; scalable=0 if item.get('scalable') is False else 1
        cur=execute("""INSERT INTO recipe_ingredients(recipe_id,sort_order,quantity_num,quantity_text,unit,ingredient,ingredient_key,note,aisle,optional,prep_note,scalable) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",(rid,i,qty_num,qty_text,unit,name,normalize_ingredient(name),note,aisle,optional,prep,scalable))
        ids.append(cur.lastrowid)
    return ids

def replace_steps(rid, steps, ingredient_ids):
    execute("DELETE FROM recipe_steps WHERE recipe_id=?",(rid,))
    for n, step in enumerate(steps,1):
        instruction=(step.get('instruction') or '').strip()
        if not instruction: continue
        temp=step.get('temp_f'); dur=step.get('duration_minutes')
        try: temp=float(temp) if str(temp).strip() else None
        except: temp=None
        try: dur=float(dur) if str(dur).strip() else None
        except: dur=None
        cur=execute("""INSERT INTO recipe_steps(recipe_id,step_number,title,instruction,temp_f,duration_minutes,timer_label,doneness) VALUES(?,?,?,?,?,?,?,?)""",(rid,n,(step.get('title') or '').strip(),instruction,temp,dur,(step.get('timer_label') or '').strip(),(step.get('doneness') or '').strip()))
        sid=cur.lastrowid
        for link in step.get('ingredients') or []:
            idx=link.get('ingredient_index')
            try: idx=int(idx)
            except: continue
            if idx<0 or idx>=len(ingredient_ids) or not ingredient_ids[idx]: continue
            try: frac=float(link.get('quantity_fraction',1) or 1)
            except: frac=1
            execute("INSERT OR REPLACE INTO recipe_step_ingredients(step_id,ingredient_id,quantity_fraction,note) VALUES(?,?,?,?)",(sid,ingredient_ids[idx],max(0,frac),(link.get('note') or '').strip()))

def auto_steps_from_text(instructions, ingredients):
    steps=split_instruction_steps(instructions)
    result=[]
    norm_steps=[normalize_ingredient(x) for x in steps]
    for idx,st in enumerate(steps):
        links=[]
        for i,ing in enumerate(ingredients):
            key=normalize_ingredient(ing.get('ingredient','') if isinstance(ing,dict) else str(ing))
            terms=significant_terms(key)
            hits=[j for j,s in enumerate(norm_steps) if ingredient_mentioned(s,key)]
            if len(hits)==1 and hits[0]==idx: links.append({'ingredient_index':i,'quantity_fraction':1})
        result.append({'instruction':st,'temp_f':extract_temp_f(st),'duration_minutes':extract_duration_minutes(st),'ingredients':links})
    return result

def recipe_snapshot(rid):
    r=db().execute("SELECT * FROM recipes WHERE id=?",(rid,)).fetchone()
    if not r:return None
    ingredients=[dict(x) for x in db().execute("SELECT * FROM recipe_ingredients WHERE recipe_id=? ORDER BY sort_order,id",(rid,)).fetchall()]
    steps=[]
    id_to_index={x['id']:i for i,x in enumerate(ingredients)}
    for s in db().execute("SELECT * FROM recipe_steps WHERE recipe_id=? ORDER BY step_number,id",(rid,)).fetchall():
        sd=dict(s);sd['ingredients']=[]
        for l in db().execute("SELECT * FROM recipe_step_ingredients WHERE step_id=?",(s['id'],)).fetchall():
            if l['ingredient_id'] in id_to_index: sd['ingredients'].append({'ingredient_index':id_to_index[l['ingredient_id']],'quantity_fraction':l['quantity_fraction'],'note':l['note']})
        steps.append(sd)
    return {'recipe':dict(r),'ingredients':ingredients,'steps':steps}

def finalize_import_sources(rid, token, user_id):
    if not token:return
    st=db().execute("SELECT * FROM import_staging WHERE token=? AND user_id=?",(token,user_id)).fetchone()
    if not st:return
    files=json.loads(st['source_files_json'] or '[]')
    dest_folder=UPLOAD_DIR/'sources'/f'recipe-{rid}';dest_folder.mkdir(parents=True,exist_ok=True)
    if files:
        for src_rel in files:
            src=UPLOAD_DIR/src_rel
            if src.exists():
                dest=dest_folder/src.name; shutil.move(str(src),str(dest)); rel=dest.relative_to(UPLOAD_DIR).as_posix()
                execute("INSERT INTO recipe_sources(recipe_id,source_type,source_url,source_label,source_text,file_path,created_by,created_at) VALUES(?,?,?,?,?,?,?,?)",(rid,st['source_type'],st['source_url'],st['source_label'],st['source_text'],rel,user_id,utcnow()))
    else:
        execute("INSERT INTO recipe_sources(recipe_id,source_type,source_url,source_label,source_text,file_path,created_by,created_at) VALUES(?,?,?,?,?,?,?,?)",(rid,st['source_type'],st['source_url'],st['source_label'],st['source_text'],None,user_id,utcnow()))
    execute("DELETE FROM import_staging WHERE token=?",(token,))

@app.post("/api/recipes")
@login_required
def create_recipe():
    body=request.get_json(silent=True) or {}; x=normalize_recipe_payload(body)
    if not x['title']: return jsonify(error='Recipe title is required'),400
    if not x['ingredients'] and not x['instructions'] and not x['steps'] and not x['source_url']: return jsonify(error='Add ingredients, steps, or a source'),400
    status='pending' if g.user['role']=='guest' else ('draft' if body.get('draft') else 'shared')
    steps=x['steps'] or auto_steps_from_text(x['instructions'],x['ingredients'])
    quality='structured' if x['servings_base'] and x['ingredients'] and steps else 'needs_review'
    cur=execute("""INSERT INTO recipes(title,description,category,subcategory,equipment,servings_base,servings_label,prep_text,cook_text,total_text,instructions,notes,tags,source_url,owner_id,status,visibility,created_at,updated_at,original_author,approx_year,family_branch,occasion,family_story,cuisine,quality_status,parent_recipe_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(x['title'],x['description'],x['category'],x['subcategory'],x['equipment'],x['servings_base'],x['servings_label'] or (str(x['servings_base']) if x['servings_base'] else ''),x['prep_text'],x['cook_text'],x['total_text'],x['instructions'],x['notes'],x['tags'],x['source_url'],g.user['id'],status,x['visibility'],utcnow(),utcnow(),x['original_author'],x['approx_year'],x['family_branch'],x['occasion'],x['family_story'],x['cuisine'],quality,x['parent_recipe_id']))
    rid=cur.lastrowid; ids=replace_ingredients(rid,x['ingredients']); replace_steps(rid,steps,ids); finalize_import_sources(rid,x['import_token'],g.user['id'])
    return jsonify(ok=True,id=rid,status=status,quality_status=quality),201

@app.put("/api/recipes/<int:rid>")
@login_required
def update_recipe(rid):
    r=db().execute("SELECT * FROM recipes WHERE id=?",(rid,)).fetchone()
    if not r:return jsonify(error='Recipe not found'),404
    if not can_edit_recipe(g.user,r):return jsonify(error='You cannot edit this recipe'),403
    body=request.get_json(silent=True) or {};x=normalize_recipe_payload(body)
    if not x['title']:return jsonify(error='Recipe title is required'),400
    snap=recipe_snapshot(rid)
    if snap: execute("INSERT INTO recipe_revisions(recipe_id,changed_by,snapshot_json,reason,created_at) VALUES(?,?,?,?,?)",(rid,g.user['id'],json.dumps(snap,default=str),(body.get('revision_reason') or 'Recipe edited').strip(),utcnow()))
    steps=x['steps'] or auto_steps_from_text(x['instructions'],x['ingredients']); quality='structured' if x['servings_base'] and x['ingredients'] and steps else 'needs_review'
    execute("""UPDATE recipes SET title=?,description=?,category=?,subcategory=?,equipment=?,servings_base=?,servings_label=?,prep_text=?,cook_text=?,total_text=?,instructions=?,notes=?,tags=?,source_url=?,visibility=?,updated_at=?,original_author=?,approx_year=?,family_branch=?,occasion=?,family_story=?,cuisine=?,quality_status=?,parent_recipe_id=? WHERE id=?""",(x['title'],x['description'],x['category'],x['subcategory'],x['equipment'],x['servings_base'],x['servings_label'] or (str(x['servings_base']) if x['servings_base'] else ''),x['prep_text'],x['cook_text'],x['total_text'],x['instructions'],x['notes'],x['tags'],x['source_url'],x['visibility'],utcnow(),x['original_author'],x['approx_year'],x['family_branch'],x['occasion'],x['family_story'],x['cuisine'],quality,x['parent_recipe_id'],rid))
    ids=replace_ingredients(rid,x['ingredients']);replace_steps(rid,steps,ids);finalize_import_sources(rid,x['import_token'],g.user['id'])
    return jsonify(ok=True,quality_status=quality)

@app.delete("/api/recipes/<int:rid>")
@login_required
def archive_recipe(rid):
    r = db().execute("SELECT * FROM recipes WHERE id=?", (rid,)).fetchone()
    if not r or not can_edit_recipe(g.user, r):
        return jsonify(error="Recipe not found or not editable"), 404
    execute("UPDATE recipes SET status='archived',updated_at=? WHERE id=?", (utcnow(),rid))
    return jsonify(ok=True)

@app.get("/api/pending")
@admin_required
def pending_recipes():
    rows = db().execute("""
        SELECT r.*,u.display_name owner_name FROM recipes r
        LEFT JOIN users u ON u.id=r.owner_id
        WHERE r.status='pending' ORDER BY r.created_at
    """).fetchall()
    return jsonify([dict(r) for r in rows])

@app.post("/api/pending/<int:rid>/approve")
@admin_required
def approve_recipe(rid):
    execute("UPDATE recipes SET status='shared',updated_at=? WHERE id=? AND status='pending'", (utcnow(),rid))
    return jsonify(ok=True)

@app.post("/api/pending/<int:rid>/reject")
@admin_required
def reject_recipe(rid):
    execute("UPDATE recipes SET status='archived',updated_at=? WHERE id=? AND status='pending'", (utcnow(),rid))
    return jsonify(ok=True)


def recipe_quality_warnings(item):
    warnings=[]
    if not item.get('servings_base'): warnings.append('Add a numeric base serving count so this recipe can scale accurately.')
    for ing in item.get('ingredients',[]):
        if not ing.get('optional') and ing.get('quantity_num') is None and not (ing.get('quantity_text') or '').strip(): warnings.append(f"Add a measurable quantity for {ing.get('ingredient')}.")
    linked={s['id']:{x['ingredient_id'] for x in s.get('ingredients',[])} for s in item.get('steps',[])}
    allings=item.get('ingredients',[])
    for s in item.get('steps',[]):
        ns=normalize_ingredient(s.get('instruction',''))
        for ing in allings:
            terms=significant_terms(ing.get('ingredient_key',''))
            if ingredient_mentioned(ns,ing.get('ingredient_key','')) and ing['id'] not in linked.get(s['id'],set()): warnings.append(f"Step {s.get('step_number')} mentions {ing.get('ingredient')} but does not have a linked amount.")
        if re.search(r'\b(bake|roast|oven)\b',s.get('instruction',''),re.I) and not s.get('temp_f') and not extract_temp_f(s.get('instruction','')): warnings.append(f"Step {s.get('step_number')} appears to use the oven but has no explicit temperature.")
    return warnings[:20]

def get_pairings(rid):
    manual=[dict(x) for x in db().execute("""SELECT p.id,p.pairing_type,p.note,1 manual,r.id recipe_id,r.title,r.category,r.cover_image,u.display_name owner_name,u.avatar_path owner_avatar,COALESCE((SELECT AVG(rating) FROM ratings WHERE recipe_id=r.id),0) rating_avg FROM recipe_pairings p JOIN recipes r ON r.id=p.paired_recipe_id LEFT JOIN users u ON u.id=r.owner_id WHERE p.recipe_id=? AND r.status='shared' ORDER BY p.pairing_type,r.title""",(rid,)).fetchall()]
    have={x['pairing_type'] for x in manual}
    base=db().execute("SELECT category,cuisine,tags FROM recipes WHERE id=?",(rid,)).fetchone()
    if not base:return manual
    desired=[]
    if base['category']=='Main Dishes': desired=[('Side','Sides'),('Drink','Drinks'),('Dessert','Desserts')]
    elif base['category']=='Breakfast & Brunch': desired=[('Drink','Drinks')]
    elif base['category']=='Desserts': desired=[('Drink','Drinks')]
    suggestions=[]
    base_tags=set(normalize_ingredient(base['tags'] or '').split())
    for typ,cat in desired:
        if typ in have:continue
        candidates=db().execute("""SELECT r.id recipe_id,r.title,r.category,r.cover_image,u.display_name owner_name,u.avatar_path owner_avatar,r.tags,r.cuisine,COALESCE(AVG(rt.rating),0) rating_avg,COUNT(rt.user_id) rating_count FROM recipes r LEFT JOIN users u ON u.id=r.owner_id LEFT JOIN ratings rt ON rt.recipe_id=r.id WHERE r.status='shared' AND r.category=? AND r.id<>? GROUP BY r.id""",(cat,rid)).fetchall()
        scored=[]
        for c in candidates:
            tags=set(normalize_ingredient(c['tags'] or '').split()); overlap=len(base_tags & tags); cuisine_bonus=2 if base['cuisine'] and c['cuisine'] and base['cuisine'].lower()==c['cuisine'].lower() else 0
            score=float(c['rating_avg'] or 0)+(overlap*.35)+cuisine_bonus
            scored.append((score,c))
        if scored:
            c=max(scored,key=lambda x:x[0])[1];d=dict(c);d.update(pairing_type=typ,note='',manual=0);suggestions.append(d)
    return manual+suggestions

@app.post("/api/recipes/<int:rid>/pairings")
@login_required
def save_pairing(rid):
    r=db().execute("SELECT * FROM recipes WHERE id=?",(rid,)).fetchone()
    if not r or not can_edit_recipe(g.user,r):return jsonify(error='Not allowed'),403
    body=request.get_json(silent=True) or {};pid=int(body.get('paired_recipe_id') or 0);typ=(body.get('pairing_type') or 'Pairing').strip()[:30]
    if not db().execute("SELECT 1 FROM recipes WHERE id=? AND status='shared'",(pid,)).fetchone():return jsonify(error='Paired recipe not found'),404
    execute("INSERT OR REPLACE INTO recipe_pairings(recipe_id,paired_recipe_id,pairing_type,note,created_by,created_at) VALUES(?,?,?,?,?,?)",(rid,pid,typ,(body.get('note') or '').strip(),g.user['id'],utcnow()))
    return jsonify(ok=True)

@app.delete("/api/recipe-pairings/<int:pid>")
@login_required
def delete_pairing(pid):
    p=db().execute("SELECT p.*,r.owner_id FROM recipe_pairings p JOIN recipes r ON r.id=p.recipe_id WHERE p.id=?",(pid,)).fetchone()
    if not p or (g.user['role']!='admin' and p['owner_id']!=g.user['id']):return jsonify(error='Not found'),404
    execute("DELETE FROM recipe_pairings WHERE id=?",(pid,));return jsonify(ok=True)

@app.post("/api/recipes/<int:rid>/my-note")
@login_required
def save_personal_note(rid):
    body=(request.get_json(silent=True) or {}).get('body','').strip()
    if body: execute("INSERT INTO personal_recipe_notes(recipe_id,user_id,body,updated_at) VALUES(?,?,?,?) ON CONFLICT(recipe_id,user_id) DO UPDATE SET body=excluded.body,updated_at=excluded.updated_at",(rid,g.user['id'],body,utcnow()))
    else: execute("DELETE FROM personal_recipe_notes WHERE recipe_id=? AND user_id=?",(rid,g.user['id']))
    return jsonify(ok=True)

@app.post("/api/recipes/<int:rid>/revisions/<int:revision_id>/restore")
@login_required
def restore_revision(rid,revision_id):
    r=db().execute("SELECT * FROM recipes WHERE id=?",(rid,)).fetchone()
    if not r or not can_edit_recipe(g.user,r):return jsonify(error='Not allowed'),403
    rv=db().execute("SELECT * FROM recipe_revisions WHERE id=? AND recipe_id=?",(revision_id,rid)).fetchone()
    if not rv:return jsonify(error='Revision not found'),404
    current=recipe_snapshot(rid);execute("INSERT INTO recipe_revisions(recipe_id,changed_by,snapshot_json,reason,created_at) VALUES(?,?,?,?,?)",(rid,g.user['id'],json.dumps(current,default=str),'Before restoring revision',utcnow()))
    snap=json.loads(rv['snapshot_json']);rr=snap['recipe'];cols=['title','description','category','subcategory','equipment','servings_base','servings_label','prep_text','cook_text','total_text','instructions','notes','tags','source_url','visibility','original_author','approx_year','family_branch','occasion','family_story','cuisine','quality_status','parent_recipe_id']
    sets=','.join(f'{c}=?' for c in cols);execute(f"UPDATE recipes SET {sets},updated_at=? WHERE id=?",tuple(rr.get(c) for c in cols)+(utcnow(),rid))
    ids=replace_ingredients(rid,snap['ingredients']);replace_steps(rid,snap['steps'],ids);return jsonify(ok=True)

# ---------- Ratings, comments, favorites, made it ----------

@app.post("/api/recipes/<int:rid>/rating")
@login_required
def rate_recipe(rid):
    rating = int((request.get_json(silent=True) or {}).get("rating",0))
    if rating not in range(1,6):
        return jsonify(error="Rating must be 1-5"), 400
    execute("""
        INSERT INTO ratings(recipe_id,user_id,rating,updated_at) VALUES(?,?,?,?)
        ON CONFLICT(recipe_id,user_id) DO UPDATE SET rating=excluded.rating,updated_at=excluded.updated_at
    """, (rid,g.user["id"],rating,utcnow()))
    return jsonify(ok=True)

@app.post("/api/recipes/<int:rid>/comments")
@login_required
def add_comment(rid):
    body = ((request.get_json(silent=True) or {}).get("body") or "").strip()
    if not body:
        return jsonify(error="Comment cannot be empty"), 400
    if len(body) > 3000:
        return jsonify(error="Comment is too long"), 400
    cur = execute("INSERT INTO comments(recipe_id,user_id,body,created_at,updated_at) VALUES(?,?,?,?,?)",
                  (rid,g.user["id"],body,utcnow(),utcnow()))
    return jsonify(ok=True,id=cur.lastrowid), 201

@app.delete("/api/comments/<int:cid>")
@login_required
def delete_comment(cid):
    c = db().execute("SELECT * FROM comments WHERE id=?", (cid,)).fetchone()
    if not c or (c["user_id"] != g.user["id"] and g.user["role"] != "admin"):
        return jsonify(error="Comment not found"), 404
    execute("DELETE FROM comments WHERE id=?", (cid,))
    return jsonify(ok=True)

@app.post("/api/recipes/<int:rid>/favorite")
@login_required
def toggle_favorite(rid):
    existing = db().execute("SELECT 1 FROM favorites WHERE recipe_id=? AND user_id=?", (rid,g.user["id"])).fetchone()
    if existing:
        execute("DELETE FROM favorites WHERE recipe_id=? AND user_id=?", (rid,g.user["id"]))
        return jsonify(ok=True,favorite=False)
    execute("INSERT INTO favorites(recipe_id,user_id,created_at) VALUES(?,?,?)", (rid,g.user["id"],utcnow()))
    return jsonify(ok=True,favorite=True)

@app.post("/api/recipes/<int:rid>/made")
@login_required
def made_it(rid):
    note = ((request.get_json(silent=True) or {}).get("note") or "").strip()
    execute("INSERT INTO cook_events(recipe_id,user_id,cooked_at,note) VALUES(?,?,?,?)", (rid,g.user["id"],utcnow(),note or None))
    return jsonify(ok=True)

# ---------- Ingredient discovery ----------

@app.get("/api/ingredient-suggestions")
@login_required
def ingredient_suggestions():
    q = normalize_ingredient(request.args.get("q",""))
    if not q:
        rows = db().execute("""
            SELECT ingredient,ingredient_key,COUNT(*) n FROM recipe_ingredients
            GROUP BY ingredient_key ORDER BY n DESC LIMIT 30
        """).fetchall()
    else:
        rows = db().execute("""
            SELECT ingredient,ingredient_key,COUNT(*) n FROM recipe_ingredients
            WHERE ingredient_key LIKE ? GROUP BY ingredient_key ORDER BY n DESC LIMIT 30
        """, (f"%{q}%",)).fetchall()
    return jsonify([dict(r) for r in rows])

@app.get("/api/discover")
@login_required
def discover():
    have = [normalize_ingredient(x) for x in request.args.get("ingredients","").split(",") if normalize_ingredient(x)]
    if not have:
        return jsonify([])
    rows = db().execute("""
      SELECT r.id,r.title,r.category,r.total_text,r.owner_id,u.display_name owner_name
      FROM recipes r LEFT JOIN users u ON u.id=r.owner_id
      WHERE r.status='shared' AND (r.visibility='family' OR r.owner_id=?)
      ORDER BY r.title
    """, (g.user["id"],)).fetchall()
    out = []
    for r in rows:
        ings = db().execute("SELECT ingredient,ingredient_key,optional FROM recipe_ingredients WHERE recipe_id=?", (r["id"],)).fetchall()
        required = [x for x in ings if not x["optional"]]
        if not required:
            continue
        matched, missing = [], []
        for ing in required:
            if any(h in ing["ingredient_key"] or ing["ingredient_key"] in h for h in have):
                matched.append(ing["ingredient"])
            else:
                missing.append(ing["ingredient"])
        score = round(100 * len(matched) / len(required))
        if matched:
            item = dict(r)
            item.update(match_percent=score, matched=matched, missing=missing[:8], ingredient_count=len(required))
            out.append(item)
    out.sort(key=lambda x:(-x["match_percent"], len(x["missing"]), x["title"].lower()))
    return jsonify(out[:50])

# ---------- Shopping lists ----------

def list_access(list_id, user):
    row = db().execute("SELECT * FROM shopping_lists WHERE id=?", (list_id,)).fetchone()
    if not row:
        return None
    if row["shared"] or row["owner_id"] == user["id"] or user["role"] == "admin":
        return row
    return None

@app.get("/api/shopping-lists")
@login_required
def shopping_lists():
    rows = db().execute("""
        SELECT l.*,u.display_name owner_name,
               (SELECT COUNT(*) FROM shopping_items i WHERE i.list_id=l.id AND i.checked=0) open_items
        FROM shopping_lists l JOIN users u ON u.id=l.owner_id
        WHERE l.shared=1 OR l.owner_id=?
        ORDER BY l.shared DESC,l.created_at
    """, (g.user["id"],)).fetchall()
    return jsonify([dict(r) for r in rows])

@app.post("/api/shopping-lists")
@login_required
def create_list():
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    if not name:
        return jsonify(error="List name is required"), 400
    shared = 1 if body.get("shared") and g.user["role"] in {"member","admin"} else 0
    cur = execute("INSERT INTO shopping_lists(name,owner_id,shared,created_at) VALUES(?,?,?,?)", (name,g.user["id"],shared,utcnow()))
    return jsonify(ok=True,id=cur.lastrowid), 201

@app.get("/api/shopping-lists/<int:lid>")
@login_required
def get_list(lid):
    lst = list_access(lid,g.user)
    if not lst:
        return jsonify(error="List not found"), 404
    items = db().execute("""
      SELECT i.*,u.display_name added_by_name,r.title source_recipe_name
      FROM shopping_items i
      LEFT JOIN users u ON u.id=i.added_by
      LEFT JOIN recipes r ON r.id=i.source_recipe_id
      WHERE i.list_id=? ORDER BY i.checked,i.aisle,i.display_name
    """,(lid,)).fetchall()
    return jsonify(list=dict(lst),items=[dict(i) for i in items])

def format_qty(q):
    if q is None:
        return ""
    if abs(q-round(q))<1e-9:
        return str(int(round(q)))
    return f"{q:.2f}".rstrip("0").rstrip(".")

@app.post("/api/shopping-lists/<int:lid>/items")
@login_required
def add_manual_item(lid):
    if not list_access(lid,g.user):
        return jsonify(error="List not found"), 404
    body = request.get_json(silent=True) or {}
    name = (body.get("display_name") or "").strip()
    if not name:
        return jsonify(error="Item name is required"), 400
    execute("""
      INSERT INTO shopping_items(list_id,display_name,ingredient_key,quantity_text,unit,aisle,added_by,created_at)
      VALUES(?,?,?,?,?,?,?,?)
    """,(lid,name,normalize_ingredient(name),(body.get("quantity_text") or "").strip(),(body.get("unit") or "").strip(),
         (body.get("aisle") or guess_aisle(name)).strip(),g.user["id"],utcnow()))
    return jsonify(ok=True)

@app.post("/api/shopping-lists/<int:lid>/from-recipe/<int:rid>")
@login_required
def add_recipe_to_list(lid,rid):
    if not list_access(lid,g.user):
        return jsonify(error="List not found"), 404
    r = db().execute("SELECT * FROM recipes WHERE id=? AND status='shared'",(rid,)).fetchone()
    if not r:
        return jsonify(error="Recipe not found"),404
    body = request.get_json(silent=True) or {}
    target = body.get("servings")
    factor = 1.0
    try:
        if target and r["servings_base"]:
            factor = float(target)/float(r["servings_base"])
    except:
        factor = 1.0
    ings = db().execute("SELECT * FROM recipe_ingredients WHERE recipe_id=? ORDER BY sort_order",(rid,)).fetchall()
    added=0
    for ing in ings:
        if ing["optional"] and body.get("skip_optional",False):
            continue
        qnum = ing["quantity_num"]*factor if ing["quantity_num"] is not None else None
        qtext = format_qty(qnum) if qnum is not None else ing["quantity_text"]
        # Combine only clean numeric quantities with identical unit/key.
        existing = None
        if qnum is not None:
            existing = db().execute("""
              SELECT * FROM shopping_items
              WHERE list_id=? AND checked=0 AND ingredient_key=? AND coalesce(unit,'')=coalesce(?, '')
                    AND quantity_num IS NOT NULL
              LIMIT 1
            """,(lid,ing["ingredient_key"],ing["unit"])).fetchone()
        if existing:
            newq = existing["quantity_num"] + qnum
            execute("UPDATE shopping_items SET quantity_num=?,quantity_text=? WHERE id=?", (newq,format_qty(newq),existing["id"]))
        else:
            execute("""
              INSERT INTO shopping_items(list_id,display_name,ingredient_key,quantity_num,quantity_text,unit,aisle,source_recipe_id,added_by,created_at)
              VALUES(?,?,?,?,?,?,?,?,?,?)
            """,(lid,ing["ingredient"],ing["ingredient_key"],qnum,qtext,ing["unit"],ing["aisle"],rid,g.user["id"],utcnow()))
        added += 1
    return jsonify(ok=True,added=added)

@app.patch("/api/shopping-items/<int:iid>")
@login_required
def update_shopping_item(iid):
    item = db().execute("SELECT * FROM shopping_items WHERE id=?",(iid,)).fetchone()
    if not item or not list_access(item["list_id"],g.user):
        return jsonify(error="Item not found"),404
    body = request.get_json(silent=True) or {}
    if "checked" in body:
        execute("UPDATE shopping_items SET checked=? WHERE id=?", (1 if body["checked"] else 0,iid))
    if "display_name" in body:
        execute("UPDATE shopping_items SET display_name=?,ingredient_key=? WHERE id=?",
                ((body["display_name"] or "").strip(),normalize_ingredient(body["display_name"]),iid))
    return jsonify(ok=True)

@app.delete("/api/shopping-items/<int:iid>")
@login_required
def delete_shopping_item(iid):
    item = db().execute("SELECT * FROM shopping_items WHERE id=?",(iid,)).fetchone()
    if not item or not list_access(item["list_id"],g.user):
        return jsonify(error="Item not found"),404
    execute("DELETE FROM shopping_items WHERE id=?",(iid,))
    return jsonify(ok=True)

@app.post("/api/shopping-lists/<int:lid>/clear-checked")
@login_required
def clear_checked(lid):
    if not list_access(lid,g.user):
        return jsonify(error="List not found"),404
    execute("DELETE FROM shopping_items WHERE list_id=? AND checked=1",(lid,))
    return jsonify(ok=True)

# ---------- Family story media ----------

@app.post("/api/recipes/<int:rid>/story-media")
@login_required
def upload_story_media(rid):
    recipe=db().execute("SELECT * FROM recipes WHERE id=?",(rid,)).fetchone()
    if not recipe or not can_edit_recipe(g.user,recipe):
        return jsonify(error="Recipe not found or not editable"),404

    files=request.files.getlist("media")
    if not files:
        return jsonify(error="Choose a story photo or video"),400
    if len(files)>8:
        return jsonify(error="Add up to 8 story photos/videos at a time"),400

    folder=UPLOAD_DIR/"stories"/f"recipe-{rid}"
    folder.mkdir(parents=True,exist_ok=True)
    created=[]
    errors=[]

    for f in files:
        if not f or not f.filename or "." not in f.filename:
            continue
        ext=f.filename.rsplit(".",1)[1].lower()
        if ext in ALLOWED_IMAGES:
            media_type="image"
            max_bytes=MAX_STORY_IMAGE_BYTES
        elif ext in ALLOWED_STORY_VIDEOS:
            media_type="video"
            max_bytes=MAX_STORY_VIDEO_BYTES
        else:
            errors.append(f"{f.filename}: unsupported file type")
            continue

        safe=secure_filename(Path(f.filename).stem)[:80] or "story"
        name=f"{int(time.time()*1000)}-{secrets.token_hex(3)}-{safe}.{ext}"
        dest=folder/name
        try:
            f.save(dest)
            size=dest.stat().st_size
            if size<=0 or size>max_bytes:
                dest.unlink(missing_ok=True)
                limit=max_bytes//(1024*1024)
                errors.append(f"{f.filename}: file must be {limit} MB or smaller")
                continue

            if media_type=="image" and Image is not None:
                try:
                    with Image.open(dest) as im:
                        im.verify()
                except Exception:
                    dest.unlink(missing_ok=True)
                    errors.append(f"{f.filename}: not a valid image")
                    continue

            rel=dest.relative_to(UPLOAD_DIR).as_posix()
            cur=execute(
                """INSERT INTO recipe_sources
                   (recipe_id,source_type,source_url,source_label,source_text,file_path,created_by,created_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (rid,f"story_{media_type}",None,"Family story",None,rel,g.user["id"],utcnow())
            )
            created.append({"id":cur.lastrowid,"media_type":media_type,"file_path":rel})
        except Exception:
            try: dest.unlink(missing_ok=True)
            except Exception: pass
            errors.append(f"{f.filename}: upload failed")

    if not created and errors:
        return jsonify(error="; ".join(errors)),400
    return jsonify(ok=True,created=created,warnings=errors)

@app.delete("/api/recipes/<int:rid>/story-media/<int:sid>")
@login_required
def delete_story_media(rid,sid):
    recipe=db().execute("SELECT * FROM recipes WHERE id=?",(rid,)).fetchone()
    if not recipe or not can_edit_recipe(g.user,recipe):
        return jsonify(error="Recipe not found or not editable"),404
    row=db().execute(
        "SELECT * FROM recipe_sources WHERE id=? AND recipe_id=? AND source_type IN ('story_image','story_video')",
        (sid,rid)
    ).fetchone()
    if not row:
        return jsonify(error="Story media not found"),404
    if row["file_path"]:
        try:(UPLOAD_DIR/row["file_path"]).unlink(missing_ok=True)
        except Exception:pass
    execute("DELETE FROM recipe_sources WHERE id=?",(sid,))
    return jsonify(ok=True)


# ---------- Images ----------

@app.post("/api/recipes/<int:rid>/image")
@login_required
def upload_image(rid):
    r = db().execute("SELECT * FROM recipes WHERE id=?",(rid,)).fetchone()
    if not r or not can_edit_recipe(g.user,r):
        return jsonify(error="Recipe not found or not editable"),404
    f = request.files.get("image")
    if not f or not f.filename or "." not in f.filename:
        return jsonify(error="Choose an image"),400
    ext = f.filename.rsplit(".",1)[1].lower()
    if ext not in ALLOWED_IMAGES:
        return jsonify(error="Use PNG, JPG, JPEG, or WEBP"),400
    name = secure_filename(f"recipe-{rid}-{int(time.time())}.{ext}")
    f.save(UPLOAD_DIR/name)
    old = r["cover_image"]
    execute("UPDATE recipes SET cover_image=?,updated_at=? WHERE id=?",(name,utcnow(),rid))
    if old:
        try:(UPLOAD_DIR/old).unlink(missing_ok=True)
        except:pass
    return jsonify(ok=True,filename=name)

@app.get("/uploads/<path:name>")
@login_required
def serve_upload(name):
    return send_from_directory(UPLOAD_DIR,name)

# ---------- Import URL ----------


# ---------- Import center: website, ChatGPT share links, text, and recipe-card photos ----------

def is_public_host(host):
    try:
        infos=socket.getaddrinfo(host,None)
        for info in infos:
            ip=ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast: return False
        return True
    except Exception:return False

def safe_fetch(url, allowed_host=None, max_bytes=3_000_000):
    p=urlparse(url)
    if p.scheme not in {'http','https'} or not p.hostname: raise ValueError('Enter a valid http(s) URL')
    if allowed_host and p.hostname.lower()!=allowed_host: raise ValueError('That URL is not from the expected host')
    if not is_public_host(p.hostname): raise ValueError('Private/local URLs cannot be imported')
    req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 TableAndTale/3.0','Accept-Language':'en-US,en;q=0.9'})
    with urllib.request.urlopen(req,timeout=15) as resp:
        final=resp.geturl();fp=urlparse(final)
        if allowed_host and fp.hostname.lower()!=allowed_host: raise ValueError('The URL redirected away from the expected host')
        if not is_public_host(fp.hostname): raise ValueError('Unsafe redirect blocked')
        raw=resp.read(max_bytes+1)
        if len(raw)>max_bytes: raise ValueError('Page is too large to import')
        return raw.decode('utf-8','ignore'),final

def clean_visible_text(html):
    if BeautifulSoup is None:
        return re.sub(r'<[^>]+>','\n',html)
    soup=BeautifulSoup(html,'html.parser')
    for tag in soup(['script','style','noscript','svg']): tag.decompose()
    root=soup.find('main') or soup.body or soup
    lines=[html_lib.unescape(x.strip()) for x in root.get_text('\n').splitlines() if x.strip()]
    junk={'ChatGPT','Log in','Sign up','Share','Copy link','Report conversation'}
    return '\n'.join(x for x in lines if x not in junk)

def parse_recipe_text(text):
    raw=(text or '').replace('\r','\n')
    raw=re.sub(r'\n{3,}','\n\n',raw).strip()
    lines=[re.sub(r'^\s*[•*\-]\s*','',x).strip() for x in raw.splitlines() if x.strip()]
    if not lines:return None
    ing_idx=next((i for i,x in enumerate(lines) if re.match(r'^ingredients?\s*:?',x,re.I)),None)
    dir_idx=next((i for i,x in enumerate(lines) if re.match(r'^(instructions?|directions?|method|steps?)\s*:?',x,re.I)),None)
    title='Imported Recipe'
    if ing_idx is not None:
        candidates=[x for x in lines[max(0,ing_idx-5):ing_idx] if len(x)<100 and not re.match(r'^(recipe|serves|prep|cook|total)\b',x,re.I)]
        if candidates:title=candidates[-1].strip('#: ')
    else:
        title=lines[0][:100]
    ing_lines=[];dir_lines=[]
    if ing_idx is not None:
        end=dir_idx if dir_idx is not None and dir_idx>ing_idx else len(lines)
        ing_lines=[x for x in lines[ing_idx+1:end] if not re.match(r'^[A-Za-z ]{2,25}:$',x)]
    if dir_idx is not None: dir_lines=lines[dir_idx+1:]
    if not ing_lines:
        probable=[x for x in lines if re.match(r'^(?:\d|[¼½¾⅓⅔⅛⅜⅝⅞]|one |two |a |an )',x,re.I) and len(x)<180]
        ing_lines=probable[:40]
    ingredients=[]
    for line in ing_lines:
        p=parse_ingredient_segment(line);p.update(note='',prep_note='',aisle=guess_aisle(p['ingredient']),optional='optional' in line.lower(),scalable=True);ingredients.append(p)
    instruction='\n'.join(dir_lines).strip()
    steps=auto_steps_from_text(instruction,ingredients) if instruction else []
    servings=None;serv_label=''
    for x in lines[:20]:
        m=re.search(r'\b(?:serves|servings?|yield)\s*:?\s*(\d+(?:\.\d+)?)',x,re.I)
        if m:servings=float(m.group(1));serv_label=m.group(1);break
    return {'title':title,'ingredients':ingredients,'instructions':instruction,'steps':steps,'servings_base':servings,'servings_label':serv_label,'quality_status':'needs_review'}

def parse_recipe_candidates(text):
    positions=[m.start() for m in re.finditer(r'(?im)^\s*ingredients?\s*:?\s*$',text or '')]
    chunks=[]
    if len(positions)>1:
        for i,pos in enumerate(positions):
            start=max(0,(text.rfind('\n',0,pos-1) if pos>1 else 0)); end=positions[i+1] if i+1<len(positions) else len(text)
            chunk=text[start:end]
            r=parse_recipe_text(chunk)
            if r and r.get('ingredients'):chunks.append(r)
    else:
        r=parse_recipe_text(text)
        if r:chunks=[r]
    out=[];seen=set()
    for r in chunks:
        key=(r.get('title') or '').lower()+str(len(r.get('ingredients') or []))
        if key not in seen:seen.add(key);out.append(r)
    return out[:10]

def stage_import(user_id,source_type,source_url=None,source_label=None,source_text=None,files=None):
    token=secrets.token_urlsafe(20)
    execute("INSERT INTO import_staging(token,user_id,source_type,source_url,source_label,source_text,source_files_json,created_at) VALUES(?,?,?,?,?,?,?,?)",(token,user_id,source_type,source_url,source_label,source_text,json.dumps(files or []),utcnow()))
    return token

@app.post('/api/import-ai-json')
@login_required
def import_ai_json():
    body=request.get_json(silent=True) or {}
    raw=(body.get('text') or '').strip()
    if not raw:
        return jsonify(error='Paste Table & Tale recipe JSON first'),400

    try:
        draft,warnings=parse_ai_json(raw)
    except ValueError as e:
        return jsonify(error=str(e),error_type='validation'),400
    except Exception as e:
        app.logger.exception('AI JSON parse failed')
        return jsonify(error=f'AI JSON import failed while validating the recipe: {e}',error_type='server'),500

    # The preview should never fail merely because provenance staging is unavailable
    # or the database is temporarily busy. Staging is best-effort here.
    token=None
    try:
        token=stage_import(
            g.user['id'],'ai_json',
            source_label='AI recipe JSON',
            source_text=raw[:100000]
        )
    except Exception:
        app.logger.exception('AI JSON provenance staging failed; continuing without token')
        warnings=list(warnings or []) + [
            'The recipe loaded, but Table & Tale could not stage the original JSON as source provenance. Review and save normally.'
        ]

    return jsonify(ok=True,token=token,candidates=[draft],warnings=warnings)

@app.post('/api/ai/generate-recipe')
@login_required
def ai_generate():
    if g.user['role']=='guest':
        return jsonify(error='AI recipe creation is currently available to Members and Admins during beta.'),403

    cfg=ai_settings_json()
    if not cfg['enabled']:
        return jsonify(error='Local AI recipe creation is disabled. Ask the family admin to enable it.'),403
    if too_many_ai_requests(g.user['id']):
        return jsonify(error='AI beta limit reached. Try again later.'),429

    body=request.get_json(silent=True) or {}
    prompt=(body.get('prompt') or '').strip()
    if not prompt:
        return jsonify(error='Tell Table & Tale what you want to make.'),400

    if not AI_GENERATION_LOCK.acquire(blocking=False):
        return jsonify(error='The recipe AI is already creating another recipe. Try again when it finishes.'),429

    record_ai_request(g.user['id'])
    try:
        draft,warnings,meta=ai_generate_recipe(
            cfg['ollama_url'],cfg['text_model'],body,cfg['timeout_seconds']
        )
        token=stage_import(
            g.user['id'],'ai_generated',
            source_label=f"Local AI · {meta.get('model') or cfg['text_model']}",
            source_text=prompt[:100000]
        )
        return jsonify(token=token,candidates=[draft],warnings=warnings,meta=meta)
    except (ValueError,RuntimeError) as e:
        return jsonify(error=str(e)),502
    except Exception as e:
        return jsonify(error=f'Local AI generation failed: {e}'),500
    finally:
        AI_GENERATION_LOCK.release()


def find_tesseract():
    if pytesseract is None:return None
    candidates=[shutil.which('tesseract'),r'C:\\Program Files\\Tesseract-OCR\\tesseract.exe',r'C:\\Program Files (x86)\\Tesseract-OCR\\tesseract.exe']
    for c in candidates:
        if c and Path(c).exists():return c
    return None

@app.post('/api/import-text')
@login_required
def import_text():
    body=request.get_json(silent=True) or {};raw=(body.get('text') or '').strip()
    if not raw:return jsonify(error='Paste recipe text first'),400
    cands=parse_recipe_candidates(raw);token=stage_import(g.user['id'],'text',source_label='Pasted text',source_text=raw[:100000])
    return jsonify(token=token,candidates=cands)

@app.post('/api/import-chatgpt')
@login_required
def import_chatgpt():
    body=request.get_json(silent=True) or {};url=(body.get('url') or '').strip();p=urlparse(url)
    if p.scheme!='https' or p.hostname!='chatgpt.com' or not p.path.startswith('/share/'):
        return jsonify(error='Use a ChatGPT shared conversation URL that starts with https://chatgpt.com/share/'),400
    try:html,final=safe_fetch(url,'chatgpt.com');visible=clean_visible_text(html);cands=parse_recipe_candidates(visible)
    except Exception as e:return jsonify(error=f'Could not read that ChatGPT shared link: {e}'),502
    if not cands:return jsonify(error='The shared page loaded, but I could not confidently find a recipe. Try Paste Text instead.'),422
    token=stage_import(g.user['id'],'chatgpt',source_url=final,source_label='ChatGPT shared conversation',source_text='\n\n'.join((c.get('title','')+'\n'+c.get('instructions','')) for c in cands)[:100000])
    return jsonify(token=token,candidates=cands)

@app.post('/api/import-photo')
@login_required
def import_photo():
    files=request.files.getlist('images')
    if not files:return jsonify(error='Choose at least one recipe-card photo'),400
    tess=find_tesseract()
    if not tess or Image is None or ImageOps is None:return jsonify(error='OCR is not installed on this server. Run the v3 installer again to add Tesseract OCR.'),503
    pytesseract.pytesseract.tesseract_cmd=tess
    folder=UPLOAD_DIR/'staging'/f"u{g.user['id']}-{uuid.uuid4().hex}";folder.mkdir(parents=True,exist_ok=True)
    rels=[];texts=[]
    for n,f in enumerate(files[:6],1):
        if not f.filename or '.' not in f.filename:continue
        ext=f.filename.rsplit('.',1)[1].lower()
        if ext not in ALLOWED_IMAGES:continue
        dest=folder/f"page-{n}.{ext}";f.save(dest);rels.append(str(dest.relative_to(UPLOAD_DIR)).replace('\\','/'))
        try:
            im=Image.open(dest);im=ImageOps.exif_transpose(im);gray=ImageOps.autocontrast(ImageOps.grayscale(im));texts.append(pytesseract.image_to_string(gray,config='--psm 6'))
        except Exception as e:texts.append(f'[OCR error on page {n}: {e}]')
    raw='\n\n'.join(texts).strip();cands=parse_recipe_candidates(raw)
    token=stage_import(g.user['id'],'photo',source_label='Original recipe card/photo',source_text=raw[:100000],files=rels)
    return jsonify(token=token,candidates=cands,ocr_text=raw)

def extract_recipe_jsonld(html):
    matches = re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.I|re.S)
    for text in matches:
        try:
            data = json.loads(text.strip())
        except:
            continue
        stack = data if isinstance(data,list) else [data]
        i=0
        while i<len(stack):
            obj=stack[i]; i+=1
            if isinstance(obj,dict) and isinstance(obj.get("@graph"),list):
                stack.extend(obj["@graph"])
            if isinstance(obj,dict):
                t=obj.get("@type")
                if t=="Recipe" or (isinstance(t,list) and "Recipe" in t):
                    return obj
    return None

@app.post("/api/import-url")
@login_required
def import_url():
    body=request.get_json(silent=True) or {};url=(body.get('url') or '').strip()
    try:html,final=safe_fetch(url)
    except Exception as e:return jsonify(error=f'Could not import that page: {e}'),502
    rec=extract_recipe_jsonld(html)
    if rec:
        inst=rec.get('recipeInstructions','')
        if isinstance(inst,list): inst='\n'.join([(x if isinstance(x,str) else (x.get('text') or x.get('name') or '')) for x in inst]).strip()
        ingredients=[]
        for x in rec.get('recipeIngredient',[]) or []:
            p=parse_ingredient_segment(x);p.update(note='',prep_note='',aisle=guess_aisle(p['ingredient']),optional='optional' in x.lower(),scalable=True);ingredients.append(p)
        draft={'title':rec.get('name',''),'description':rec.get('description',''),'servings_label':', '.join(rec.get('recipeYield',[])) if isinstance(rec.get('recipeYield'),list) else rec.get('recipeYield',''),'prep_text':rec.get('prepTime',''),'cook_text':rec.get('cookTime',''),'total_text':rec.get('totalTime',''),'ingredients':ingredients,'instructions':inst,'steps':auto_steps_from_text(inst,ingredients),'source_url':final,'quality_status':'needs_review'}
        draft['servings_base']=parse_servings(draft['servings_label'])
    else:
        visible=clean_visible_text(html);cands=parse_recipe_candidates(visible)
        if not cands:return jsonify(error='No standard Recipe data was found. Try Paste Text or Recipe Card import.'),422
        draft=cands[0];draft['source_url']=final
    token=stage_import(g.user['id'],'website',source_url=final,source_label='Recipe website',source_text=(draft.get('title','')+'\n'+draft.get('instructions',''))[:100000])
    return jsonify(token=token,candidates=[draft])

# ---------- Activity ----------

@app.get("/api/activity")
@login_required
def activity():
    rows = db().execute("""
      SELECT * FROM (
        SELECT r.created_at ts,'recipe' type,u.display_name user_name,u.avatar_path,r.title detail,r.id recipe_id
        FROM recipes r JOIN users u ON u.id=r.owner_id WHERE r.status='shared'
        UNION ALL
        SELECT c.created_at ts,'comment' type,u.display_name user_name,u.avatar_path,r.title detail,r.id recipe_id
        FROM comments c JOIN users u ON u.id=c.user_id JOIN recipes r ON r.id=c.recipe_id
        UNION ALL
        SELECT ce.cooked_at ts,'made' type,u.display_name user_name,u.avatar_path,r.title detail,r.id recipe_id
        FROM cook_events ce JOIN users u ON u.id=ce.user_id JOIN recipes r ON r.id=ce.recipe_id
        UNION ALL
        SELECT rt.updated_at ts,'rating' type,u.display_name user_name,u.avatar_path,r.title || '|' || rt.rating detail,r.id recipe_id
        FROM ratings rt JOIN users u ON u.id=rt.user_id JOIN recipes r ON r.id=rt.recipe_id
      ) ORDER BY ts DESC LIMIT 40
    """).fetchall()
    return jsonify([dict(r) for r in rows])

@app.get("/health")
def health():
    try:
        db().execute("SELECT 1").fetchone()
        users=db().execute("SELECT COUNT(*) FROM users").fetchone()[0]
        ver=setting_get('site_name','Table & Tale')
        schema=db().execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()
        return jsonify(ok=True,app_version=APP_VERSION,schema_version=(schema[0] if schema else 'unknown'),users=users,site_name=ver)
    except Exception as e:
        return jsonify(ok=False,error=str(e)),500

# SPA fallback
@app.get("/")
def index():
    return app.send_static_file("index.html")

@app.get("/<path:path>")
def spa(path):
    candidate = ROOT/"app"/"static"/path
    if candidate.exists() and candidate.is_file():
        return send_from_directory(ROOT/"app"/"static",path)
    return app.send_static_file("index.html")

init_db()

if __name__ == "__main__":
    from waitress import serve
    host = os.environ.get("COOKBOOK_HOST","0.0.0.0")
    port = int(os.environ.get("COOKBOOK_PORT",CONFIG.get("port",3000)))
    serve(app, host=host, port=port, threads=8)
