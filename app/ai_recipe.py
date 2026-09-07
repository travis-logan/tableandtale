from __future__ import annotations

import json
import math
import re
import urllib.error
import urllib.request
from urllib.parse import urlparse

CATEGORIES = [
    "Main Dishes","Breakfast & Brunch","Sides","Appetizers & Snacks",
    "Desserts","Drinks","Breads & Baking","Sauces & Condiments"
]

RECIPE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "title": {"type": "string"},
        "description": {"type": "string"},
        "category": {"type": "string", "enum": CATEGORIES},
        "subcategory": {"type": "string"},
        "cuisine": {"type": "string"},
        "equipment": {"type": "string"},
        "servings_base": {"type": "number", "minimum": 0.25},
        "servings_label": {"type": "string"},
        "prep_text": {"type": "string"},
        "cook_text": {"type": "string"},
        "total_text": {"type": "string"},
        "visibility": {"type": "string", "enum": ["family", "private"]},
        "original_author": {"type": "string"},
        "approx_year": {"type": "string"},
        "family_branch": {"type": "string"},
        "occasion": {"type": "string"},
        "family_story": {"type": "string"},
        "notes": {"type": "string"},
        "tags": {"type": "string"},
        "ingredients": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "quantity_num": {"type": ["number", "null"]},
                    "quantity_text": {"type": "string"},
                    "unit": {"type": "string"},
                    "ingredient": {"type": "string"},
                    "prep_note": {"type": "string"},
                    "aisle": {"type": "string"},
                    "optional": {"type": "boolean"},
                    "scalable": {"type": "boolean"}
                },
                "required": [
                    "quantity_num","quantity_text","unit","ingredient",
                    "prep_note","aisle","optional","scalable"
                ]
            }
        },
        "steps": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "title": {"type": "string"},
                    "instruction": {"type": "string"},
                    "temp_f": {"type": ["number", "null"]},
                    "duration_minutes": {"type": ["number", "null"]},
                    "timer_label": {"type": "string"},
                    "doneness": {"type": "string"},
                    "ingredients": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "ingredient_index": {"type": "integer", "minimum": 0},
                                "quantity_fraction": {
                                    "type": "number",
                                    "exclusiveMinimum": 0,
                                    "maximum": 1
                                },
                                "note": {"type": "string"}
                            },
                            "required": ["ingredient_index","quantity_fraction","note"]
                        }
                    }
                },
                "required": [
                    "title","instruction","temp_f","duration_minutes",
                    "timer_label","doneness","ingredients"
                ]
            }
        }
    },
    "required": [
        "title","description","category","subcategory","cuisine","equipment",
        "servings_base","servings_label","prep_text","cook_text","total_text",
        "visibility","original_author","approx_year","family_branch","occasion",
        "family_story","notes","tags","ingredients","steps"
    ]
}

SKILL_TEXT = r"""
You are the Table & Tale Recipe Authoring Engine.

Your job is to create practical, cookable recipes that fit Table & Tale's structured
recipe editor exactly.

CORE RULES

1. Return one recipe only.
2. Return JSON only. Do not wrap the JSON in Markdown.
3. Follow the supplied JSON schema exactly.
4. Every ingredient must have its own ingredient row.
5. Prefer numeric quantity_num values whenever the quantity can scale.
6. quantity_text is the human display quantity. Examples: "1.5", "1/2", "2".
7. scalable=false only for ingredients that should not mathematically scale, such as
   "salt to taste" when there is no fixed starting amount.
8. Every cooking step must explicitly state the amount of every ingredient used in
   that step. Never write only "add the butter" if the recipe knows the amount.
9. Each step must link the ingredient rows used by ingredient_index.
10. quantity_fraction represents the portion of that ingredient row used in that
    step. If a 4 Tbsp butter ingredient is split evenly between two steps, each step
    links that ingredient with quantity_fraction 0.5, and each instruction says
    "2 Tbsp butter".
11. Do not scale oven temperatures with servings.
12. Do not assume cook time scales linearly with servings.
13. Include temperature, duration, and a doneness cue whenever they matter.
14. For meat, poultry, seafood, eggs, or reheating where safety matters, include an
    appropriate doneness cue or internal-temperature target when useful.
15. The recipe should be specific enough that a family member can cook it without
    guessing heat level, order of operations, amounts, or major timing.
16. servings_base is the numeric scaling anchor. servings_label is the friendly text.
17. Never invent family provenance. original_author, approx_year, family_branch,
    occasion, and family_story must remain empty unless the user explicitly supplied
    that information.
18. visibility defaults to "family".
19. Use only these primary categories:
    Main Dishes
    Breakfast & Brunch
    Sides
    Appetizers & Snacks
    Desserts
    Drinks
    Breads & Baking
    Sauces & Condiments
20. Put useful substitution, make-ahead, storage, or serving guidance in notes.
21. tags is a space-separated string of concise tags.
22. Aisle names should be practical grocery-store groupings such as Produce, Meat &
    Seafood, Dairy & Eggs, Pantry, Spices, Frozen, Bakery, Beverages, or Other.
23. Keep the recipe realistic. Do not add ingredients just to sound sophisticated.
24. Respect every requested ingredient, exclusion, dietary constraint, serving count,
    equipment constraint, spice preference, and time limit.

STEP QUALITY STANDARD

Bad:
"Add the chicken and cook until done."

Good:
"Heat 1 Tbsp olive oil in a 12-inch skillet over medium-high heat. Add 1.5 lb
boneless skinless chicken thighs in a single layer and cook for 5 to 6 minutes on
the first side. Flip and cook another 4 to 6 minutes, until browned and the thickest
piece reaches 165°F."

The ingredient links for that step must point to the olive oil and chicken rows.

DIVIDED INGREDIENT EXAMPLE

Ingredient row:
quantity_num: 4
quantity_text: "4"
unit: "Tbsp"
ingredient: "unsalted butter"

If Step 1 uses half:
quantity_fraction: 0.5
instruction must say "2 Tbsp unsalted butter"

If Step 4 uses the remaining half:
quantity_fraction: 0.5
instruction must say "remaining 2 Tbsp unsalted butter"

OUTPUT

Return only the structured recipe JSON requested by the schema.
""".strip()


def normalize_ollama_url(value: str) -> str:
    value=(value or "http://127.0.0.1:11434").strip().rstrip("/")
    p=urlparse(value)
    if p.scheme != "http":
        raise ValueError("Beta local AI only permits an http:// loopback Ollama URL")
    host=(p.hostname or "").lower()
    if host not in {"127.0.0.1","localhost","::1"}:
        raise ValueError("Beta local AI only permits Ollama on this same server PC")
    if p.username or p.password or p.query or p.fragment or p.path not in {"","/"}:
        raise ValueError("Use a simple local Ollama URL such as http://127.0.0.1:11434")
    port=p.port or 11434
    return f"http://127.0.0.1:{port}"


def _request_json(url: str, *, body=None, timeout=5):
    data=None
    headers={"Accept":"application/json"}
    if body is not None:
        data=json.dumps(body).encode("utf-8")
        headers["Content-Type"]="application/json"
    req=urllib.request.Request(url, data=data, headers=headers, method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw=resp.read(2_000_000)
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail=""
        try:
            detail=e.read(10000).decode("utf-8","replace")
        except Exception:
            pass
        raise RuntimeError(f"Ollama returned HTTP {e.code}: {detail[:500]}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Could not reach Ollama: {e.reason}") from e


def model_name_matches(installed: str, requested: str) -> bool:
    a=(installed or "").strip().lower()
    b=(requested or "").strip().lower()
    return a==b or a.removesuffix(":latest")==b.removesuffix(":latest")


def ollama_status(base_url: str, model: str, timeout=3):
    base=normalize_ollama_url(base_url)
    try:
        data=_request_json(base+"/api/tags", timeout=timeout)
        names=[x.get("name") or x.get("model") or "" for x in data.get("models",[])]
        return {
            "available": True,
            "model_installed": any(model_name_matches(x,model) for x in names),
            "models": names
        }
    except Exception as e:
        return {"available":False,"model_installed":False,"models":[],"error":str(e)}


def _clean_string(value, limit=6000):
    return str(value or "").strip()[:limit]


def _number_or_none(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except Exception:
        return None


def _strip_json_comments_and_trailing_commas(raw: str) -> str:
    """Best-effort cleanup for AI-produced JSON-like text.

    This is intentionally conservative. It removes // and /* */ comments only when
    they are outside quoted strings, then removes trailing commas before ] or }.
    """
    out=[]
    i=0
    in_string=False
    escaped=False
    while i < len(raw):
        ch=raw[i]
        if in_string:
            out.append(ch)
            if escaped:
                escaped=False
            elif ch=="\\":
                escaped=True
            elif ch=='"':
                in_string=False
            i+=1
            continue
        if ch=='"':
            in_string=True
            out.append(ch)
            i+=1
            continue
        if ch=="/" and i+1 < len(raw) and raw[i+1]=="/":
            i+=2
            while i < len(raw) and raw[i] not in "\r\n":
                i+=1
            continue
        if ch=="/" and i+1 < len(raw) and raw[i+1]=="*":
            i+=2
            while i+1 < len(raw) and not (raw[i]=="*" and raw[i+1]=="/"):
                i+=1
            i=min(len(raw),i+2)
            continue
        out.append(ch)
        i+=1
    # Remove trailing commas only outside strings. A regex also changes recipe
    # prose such as "stir, }" when another formatting error triggers cleanup.
    cleaned="".join(out)
    out=[]
    in_string=False
    escaped=False
    for i,ch in enumerate(cleaned):
        if in_string:
            out.append(ch)
            if escaped:
                escaped=False
            elif ch=='\\':
                escaped=True
            elif ch=='"':
                in_string=False
        elif ch=='"':
            in_string=True
            out.append(ch)
        elif ch==',' and cleaned[i+1:].lstrip().startswith(('}',']')):
            continue
        else:
            out.append(ch)
    return ''.join(out)


def _extract_json_candidate(raw: str) -> str:
    raw=(raw or "").lstrip("\ufeff").strip()
    if raw.startswith("```"):
        raw=re.sub(r"^```(?:json|javascript|js)?\s*","",raw,flags=re.I)
        raw=re.sub(r"\s*```\s*$","",raw)

    # Common HTML copy/paste from rendered blocks.
    raw=re.sub(r"^\s*<pre[^>]*>\s*","",raw,flags=re.I)
    raw=re.sub(r"\s*</pre>\s*$","",raw,flags=re.I)

    # If commentary surrounds the JSON, take the broadest outer object/array.
    first_obj=raw.find("{")
    first_arr=raw.find("[")
    starts=[x for x in (first_obj,first_arr) if x>=0]
    if starts:
        start=min(starts)
        end_obj=raw.rfind("}")
        end_arr=raw.rfind("]")
        end=max(end_obj,end_arr)
        if end>start:
            raw=raw[start:end+1]
    return raw.strip()


def _loads_ai_json(raw: str, warnings=None):
    warnings=warnings if warnings is not None else []
    # Decode serialized JSON strings before extracting braces from their content.
    original=(raw or '').lstrip('\ufeff').strip()
    try:
        decoded=json.loads(original)
    except json.JSONDecodeError:
        pass
    else:
        if not isinstance(decoded,str):
            return decoded
        original=decoded
    candidate=_extract_json_candidate(original)
    attempts=[candidate]
    cleaned=_strip_json_comments_and_trailing_commas(candidate)
    if cleaned!=candidate:
        attempts.append(cleaned)

    first_error=None
    for index,attempt in enumerate(attempts):
        try:
            data=json.loads(attempt)
            # Sometimes an AI returns a JSON string containing JSON.
            if isinstance(data,str) and data.strip().startswith(("{","[")):
                data=json.loads(data)
            if index:
                warnings.append('Removed comments or trailing commas from the pasted JSON. Review the imported recipe before saving.')
            return data
        except json.JSONDecodeError as e:
            if first_error is None:
                first_error=e
    location=f'line {first_error.lineno}, column {first_error.colno}'
    raise ValueError(
        f'That is not valid Table & Tale recipe JSON at {location}: {first_error.msg}. '
        'Copy using the Copy button on the JSON code block, or choose the original .json file. '
        'Quotation marks inside notes or instructions must be escaped as \\" and paragraph breaks as \\n. '
        'Ask the recipe skill to regenerate valid JSON if it still fails; no recipe was imported.'
    ) from first_error


def parse_ai_json(text: str):
    formatting_warnings=[]
    data=_loads_ai_json(text,formatting_warnings)

    # Accept a one-item array or common wrapper shapes.
    if isinstance(data,list):
        if len(data)!=1:
            raise ValueError("Table & Tale can import one recipe at a time. This JSON contains multiple top-level recipes.")
        data=data[0]
    if isinstance(data,dict):
        for wrapper in ("recipe","data","result","table_and_tale_recipe"):
            wrapped=data.get(wrapper)
            if isinstance(wrapped,dict) and ("ingredients" in wrapped or "steps" in wrapped):
                data=wrapped
                break

    draft,warnings=validate_recipe_draft(data)
    return draft,formatting_warnings+warnings


def _alias(data: dict, *names, default=None):
    for name in names:
        if name in data and data.get(name) not in (None,""):
            return data.get(name)
    return default


def _normalize_ingredient_item(item):
    if isinstance(item,str):
        return {
            "quantity_num":None,"quantity_text":"","unit":"",
            "ingredient":item.strip(),"prep_note":"","aisle":"",
            "optional":False,"scalable":False
        }
    if not isinstance(item,dict):
        return None
    name=_clean_string(_alias(item,"ingredient","name","item"),240)
    if not name:
        return None
    qty=_number_or_none(_alias(item,"quantity_num","quantity","amount_num"))
    qtext=_clean_string(_alias(item,"quantity_text","amount_text","display_quantity"),80)
    if not qtext and qty is not None and math.isfinite(qty):
        qtext=f"{qty:g}"
    return {
        "quantity_num": qty if qty is None or math.isfinite(qty) else None,
        "quantity_text": qtext,
        "unit": _clean_string(_alias(item,"unit","measure"),60),
        "ingredient": name,
        "prep_note": _clean_string(_alias(item,"prep_note","prep","preparation","note"),240),
        "aisle": _clean_string(_alias(item,"aisle","grocery_aisle"),100),
        "optional": bool(item.get("optional")),
        "scalable": bool(item.get("scalable", qty is not None))
    }


def _normalize_step_item(step):
    if isinstance(step,str):
        return {
            "title":"",
            "instruction":step.strip(),
            "temp_f":None,
            "duration_minutes":None,
            "timer_label":"",
            "doneness":"",
            "ingredients":[]
        }
    if not isinstance(step,dict):
        return None
    instruction=_clean_string(_alias(step,"instruction","instructions","text","direction"),6000)
    if not instruction:
        return None
    return {
        "title":_clean_string(_alias(step,"title","name"),180),
        "instruction":instruction,
        "temp_f":_number_or_none(_alias(step,"temp_f","temperature_f","temperature")),
        "duration_minutes":_number_or_none(_alias(step,"duration_minutes","minutes","duration")),
        "timer_label":_clean_string(_alias(step,"timer_label","timer"),180),
        "doneness":_clean_string(_alias(step,"doneness","done_when","target"),600),
        "ingredients":step.get("ingredients") or step.get("ingredient_links") or []
    }


def validate_recipe_draft(data):
    if not isinstance(data,dict):
        raise ValueError("AI recipe must be a JSON object")

    warnings=[]
    normalized=dict(data)

    # Common top-level aliases produced by general-purpose AIs.
    alias_map={
        "title":("title","name"),
        "description":("description","summary"),
        "category":("category","primary_category"),
        "subcategory":("subcategory","sub_category"),
        "cuisine":("cuisine","style"),
        "equipment":("equipment","tools"),
        "servings_base":("servings_base","servings","yield_number"),
        "servings_label":("servings_label","yield","serves"),
        "prep_text":("prep_text","prep_time"),
        "cook_text":("cook_text","cook_time"),
        "total_text":("total_text","total_time"),
        "family_story":("family_story","story"),
        "original_author":("original_author","recipe_author"),
        "approx_year":("approx_year","year"),
        "family_branch":("family_branch","family"),
        "occasion":("occasion",),
        "notes":("notes","note"),
        "tags":("tags",)
    }
    for dest,names in alias_map.items():
        normalized[dest]=_alias(data,*names,default=data.get(dest))

    if "steps" not in normalized:
        normalized["steps"]=_alias(data,"instructions","directions",default=[])

    out={}
    string_fields=[
        "title","description","subcategory","cuisine","equipment","servings_label",
        "prep_text","cook_text","total_text","visibility","original_author","approx_year",
        "family_branch","occasion","family_story","notes","tags"
    ]
    for key in string_fields:
        out[key]=_clean_string(normalized.get(key), 12000 if key in {"family_story","notes"} else 2000)

    out["title"]=out["title"][:180]
    if not out["title"]:
        raise ValueError("AI recipe is missing a title")

    category=_clean_string(normalized.get("category"),100)
    out["category"]=category if category in CATEGORIES else "Main Dishes"
    if category and category not in CATEGORIES:
        warnings.append(f'Category "{category}" was not recognized, so Table & Tale set it to Main Dishes for review.')
    out["visibility"]="private" if out["visibility"]=="private" else "family"

    servings=_number_or_none(normalized.get("servings_base"))
    if servings is None or not math.isfinite(servings) or servings <= 0:
        out["servings_base"]=None
        if not out["servings_label"]:
            out["servings_label"]=""
        warnings.append("Serving yield is missing or unclear. Set Serves before relying on one-click scaling.")
    else:
        out["servings_base"]=round(servings,4)
        if not out["servings_label"]:
            out["servings_label"]=f"{out['servings_base']:g} servings"

    raw_ingredients=normalized.get("ingredients") or []
    if isinstance(raw_ingredients,dict):
        raw_ingredients=list(raw_ingredients.values())
    ingredients=[]
    for item in raw_ingredients:
        normalized_item=_normalize_ingredient_item(item)
        if normalized_item:
            ingredients.append(normalized_item)
    if not ingredients:
        raise ValueError("AI recipe must include at least one ingredient")
    if len(ingredients)>80:
        raise ValueError("AI recipe has too many ingredient rows")
    out["ingredients"]=ingredients

    raw_steps=normalized.get("steps") or []
    if isinstance(raw_steps,str):
        # Preserve paragraph or newline-separated directions as usable review steps.
        chunks=[x.strip() for x in re.split(r"\n{2,}|(?m)^\s*\d+[.)]\s*",raw_steps) if x.strip()]
        raw_steps=chunks or [raw_steps]
    steps=[]
    for raw_step in raw_steps:
        step=_normalize_step_item(raw_step)
        if not step:
            continue
        temp=step["temp_f"]
        duration=step["duration_minutes"]
        if temp is not None and (not math.isfinite(temp) or temp<0 or temp>1000):
            warnings.append(f'Ignored an invalid temperature on step {len(steps)+1}.')
            temp=None
        if duration is not None and (not math.isfinite(duration) or duration<0 or duration>10080):
            warnings.append(f'Ignored an invalid duration on step {len(steps)+1}.')
            duration=None

        links=[]
        seen=set()
        for link in step["ingredients"]:
            if not isinstance(link,dict):
                continue
            idx_raw=_alias(link,"ingredient_index","index")
            try:
                idx=int(idx_raw)
            except Exception:
                continue
            if idx<0 or idx>=len(ingredients) or idx in seen:
                continue
            seen.add(idx)
            frac=_number_or_none(_alias(link,"quantity_fraction","fraction",default=1))
            frac=1.0 if frac is None else frac
            if not math.isfinite(frac) or frac<=0 or frac>1:
                warnings.append(f"Step {len(steps)+1} had an invalid ingredient fraction for {ingredients[idx]['ingredient']}; the link was skipped.")
                continue
            links.append({
                "ingredient_index":idx,
                "quantity_fraction":round(frac,4),
                "note":_clean_string(link.get("note"),240)
            })
        steps.append({
            "title":step["title"],
            "instruction":step["instruction"],
            "temp_f":temp,
            "duration_minutes":duration,
            "timer_label":step["timer_label"],
            "doneness":step["doneness"],
            "ingredients":links
        })
    if not steps:
        raise ValueError("AI recipe must include at least one cooking step")
    if len(steps)>40:
        raise ValueError("AI recipe has too many steps")
    out["steps"]=steps

    allocations=[0.0 for _ in ingredients]
    for n,step in enumerate(steps,1):
        for link in step["ingredients"]:
            allocations[link["ingredient_index"]]+=link["quantity_fraction"]
            ing=ingredients[link["ingredient_index"]]["ingredient"].lower()
            important=[x for x in re.findall(r"[a-z0-9]+",ing) if len(x)>3]
            if important and not any(x in step["instruction"].lower() for x in important[:3]):
                warnings.append(f"Step {n} links {ingredients[link['ingredient_index']]['ingredient']} but may not name it explicitly.")
    for i,total in enumerate(allocations):
        if total>1.03:
            warnings.append(f"{ingredients[i]['ingredient']} is allocated across steps at {total:.2f}× its ingredient-row quantity.")
    for n,step in enumerate(steps,1):
        lower=step["instruction"].lower()
        if any(word in lower for word in ("bake","roast","oven")) and step["temp_f"] is None and "°f" not in lower and "degrees" not in lower:
            warnings.append(f"Step {n} appears to use an oven but does not specify a temperature.")

    # De-duplicate while preserving order.
    seen_w=set()
    warnings=[w for w in warnings if not (w in seen_w or seen_w.add(w))]
    return out, warnings


def build_user_prompt(req):
    prompt=_clean_string(req.get("prompt"),4000)
    if not prompt:
        raise ValueError("Tell Table & Tale what you want to make")

    constraints=[]
    servings=_number_or_none(req.get("servings"))
    if servings and servings>0:
        constraints.append(f"Target servings: {servings:g}")
    max_time=_number_or_none(req.get("max_time_minutes"))
    if max_time and max_time>0:
        constraints.append(f"Maximum total time: {max_time:g} minutes")
    for label,key in [
        ("Preferred primary category","category"),
        ("Cuisine or style","cuisine"),
        ("Spice preference","spice_level"),
        ("Ingredients to use","use_ingredients"),
        ("Ingredients to avoid","avoid_ingredients"),
        ("Equipment available","equipment")
    ]:
        val=_clean_string(req.get(key),1000)
        if val:
            constraints.append(f"{label}: {val}")

    extra="\n".join(f"- {x}" for x in constraints)
    return f"""Create one Table & Tale recipe for this request:

{prompt}

Constraints:
{extra if extra else "- No additional constraints were supplied."}

Prioritize practical home cooking, clear amounts, explicit temperatures and times,
and steps that can be followed one screen at a time in Cook Mode.
"""


def generate_recipe(base_url: str, model: str, request_data: dict, timeout=180):
    base=normalize_ollama_url(base_url)
    model=(model or "qwen3:8b").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,120}",model):
        raise ValueError("Invalid Ollama model name")

    prompt=build_user_prompt(request_data)
    payload={
        "model":model,
        "stream":False,
        "think":False,
        "keep_alive":"5m",
        "format":RECIPE_SCHEMA,
        "options":{"temperature":0.25},
        "messages":[
            {"role":"system","content":SKILL_TEXT},
            {"role":"user","content":prompt}
        ]
    }
    response=_request_json(base+"/api/chat",body=payload,timeout=max(30,int(timeout)))
    content=((response.get("message") or {}).get("content") or "").strip()
    if not content:
        raise RuntimeError("Ollama returned an empty recipe")
    draft,warnings=parse_ai_json(content)
    return draft,warnings,{
        "model":response.get("model") or model,
        "total_duration":response.get("total_duration"),
        "prompt_eval_count":response.get("prompt_eval_count"),
        "eval_count":response.get("eval_count")
    }
