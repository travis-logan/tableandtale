---
name: table-and-tale-recipe
description: Create structured recipes for import into Table & Tale, including scaled ingredients and linked cooking steps.
---

# Table & Tale Recipe Authoring Skill

## Purpose

Use this skill whenever a recipe should be created for direct import into Table & Tale.

The required output is structured JSON that maps one-to-one to Table & Tale's recipe
editor, including ingredient quantities, scaling metadata, step-specific ingredient
links, temperatures, timers, and doneness cues.

## Output contract

Return **one JSON object in a fenced `json` code block** when the user asks for "Table & Tale format", "Table & Tale JSON",
or asks for a recipe intended to be imported into Table & Tale.

Use the code block so the user can use its Copy button without copying rendered prose.
Do not add commentary inside the code block. If the user explicitly requests raw JSON,
return raw JSON instead.

Escape quotation marks inside strings as `\"`, backslashes as `\\`, and paragraph
breaks as `\n`. Do not use literal newlines within strings, smart quotes as JSON
delimiters, comments, or trailing commas. Preserve quoted recipe and family text.

When file-generation tools are available, serialize the recipe with a JSON library,
parse the exact generated content to verify syntax, check it against the included
schema, and provide a UTF-8 `.json` download as well. Never claim validation ran if
it did not. The code block and file must contain the same recipe.

The canonical schema is stored beside this skill as:

`table-and-tale-recipe.schema.json`

## Authoring rules

1. Create one recipe per JSON object.
2. Use a positive numeric `servings_base`.
3. Use numeric `quantity_num` whenever an ingredient can scale mathematically.
4. `quantity_text` is the human-facing quantity.
5. Every ingredient mentioned in a cooking step must have an ingredient row.
6. Every ingredient used in a step must be linked by `ingredient_index`.
7. Every step must say the **actual amount used in that step**.
8. When an ingredient is divided, use `quantity_fraction` to show the portion used.
9. Temperatures do not mathematically scale when servings change.
10. Cook times do not automatically scale with servings.
11. Include heat level, temperature, duration, and doneness cues whenever useful.
12. Keep steps short enough for one-at-a-time Cook Mode.
13. Do not invent family history or provenance.
14. Use only Table & Tale's supported primary categories.
15. Put substitutions, storage, make-ahead, and serving notes in `notes`.
16. Use concise, space-separated `tags`.
17. Respect exclusions, dietary constraints, equipment limitations, spice preferences,
    serving counts, and time limits exactly.

## Quantity linkage example

If the ingredient list contains:

- 4 Tbsp unsalted butter

and the recipe uses half in Step 1 and half in Step 4:

Step 1 links that ingredient with:

```json
{"ingredient_index": 3, "quantity_fraction": 0.5, "note": ""}
```

and the instruction must explicitly say:

`Melt 2 Tbsp unsalted butter...`

Step 4 links the same ingredient with `quantity_fraction: 0.5` and explicitly says:

`Add the remaining 2 Tbsp unsalted butter...`

## Cooking instruction quality

Avoid:

`Add chicken and cook until done.`

Prefer:

`Heat 1 Tbsp olive oil in a 12-inch skillet over medium-high heat. Add 1.5 lb
boneless skinless chicken thighs in a single layer and cook for 5 to 6 minutes on
the first side. Flip and cook another 4 to 6 minutes, until browned and the thickest
piece reaches 165°F.`

The step should link both the olive oil and chicken ingredient rows.

## Import workflow

Generate the JSON, then in Table & Tale use:

**Add Recipe → Paste AI Recipe JSON → Import AI JSON**

Table & Tale validates the structure and loads the result into the normal recipe
editor for human review before saving.
