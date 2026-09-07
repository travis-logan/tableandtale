---
name: table-and-tale-recipe-card-archivist
description: Analyze photos of handwritten recipe cards, cookbook pages, notes, and family recipe artifacts, then produce a conservative, review-ready Table & Tale recipe import without inventing missing details.
---

# Table & Tale Recipe Card Archivist

## Purpose

Use this skill when the user uploads one or more images of an existing family recipe
and wants it preserved or imported into Table & Tale.

This is an **archival extraction task**, not a creative recipe-writing task.

The goal is to:

1. read the images carefully,
2. preserve what the source actually says,
3. separate recipe content from family history and editorial notes,
4. identify uncertainty instead of guessing,
5. produce Table & Tale-compatible structured recipe JSON after critical ambiguities
   have been resolved.

The canonical import schema is included with this skill as:

`table-and-tale-recipe.schema.json`

## Trigger examples

Use this skill for requests such as:

- "Convert this recipe card for Table & Tale."
- "Analyze these handwritten recipe photos."
- "Archive Grandma's recipe."
- "Turn these cookbook pages into Table & Tale JSON."
- "Extract this family recipe and its story."
- "Read the front and back of this recipe card."

## Inputs

The user may provide:

- one recipe-card image,
- front and back images,
- multiple pages of a cookbook,
- close-up images of faded or unclear areas,
- photos containing handwritten notes,
- photos that are family-story context rather than recipe instructions,
- optional user context about who wrote the recipe, when it was used, or what a
  difficult word says.

Treat all supplied images as one evidence set unless the user says they are separate
recipes.

## Non-negotiable archival rules

### 1. Never silently invent missing recipe information

Do not create an oven temperature, cooking time, serving yield, ingredient amount,
ingredient, technique, or family-history fact merely because it would make the recipe
more complete.

If the card says:

`Bake until done.`

preserve that instruction.

Do **not** silently rewrite it as:

`Bake at 350°F for 30 minutes.`

A modernized suggestion may be offered separately only if the user asks for one.

### 2. Conservative procedural reconstruction is allowed

The goal is to preserve the recipe, not merely reproduce gaps that make it impossible
to follow.

You **may add or clarify a procedural step** when all of the following are true:

1. the missing action is strongly implied by the surrounding recipe,
2. there is only one reasonable interpretation,
3. the action uses only ingredients already present in the source,
4. you do not invent a new quantity, temperature, time, flavor, or technique choice,
5. the clarification does not change the recipe's intended outcome.

Examples of acceptable clarification:

- The ingredient list contains flour, sugar, eggs, and butter, and the next written
  instruction is "Pour into pan." You may insert a neutral bridge such as:
  `Combine the listed batter ingredients until evenly mixed, then pour into the pan.`
- A card says `add eggs, milk and vanilla` but does not explicitly say to stir them
  together. You may clarify:
  `Add the listed eggs, milk, and vanilla and mix until combined.`
- A recipe lists a topping mixture and later says `put on top` without a separate step.
  You may create a distinct topping step using only the listed topping ingredients.
- A long handwritten sentence contains several clear sequential actions. You may split
  it into multiple Table & Tale steps for Cook Mode without changing the actions.

Examples that are **not** acceptable without clarification:

- deciding that butter should be melted instead of softened,
- deciding to cream butter and sugar when the source does not indicate that method,
- adding a browning/searing step because it would taste better,
- adding garlic, seasoning, oil, liquid, or garnish not shown in the source,
- inventing an oven temperature or cooking time,
- choosing a pan size that is not supported by the source,
- deciding whether something should be covered or uncovered,
- adding an internal-temperature target unless the user specifically asks for a modern
  safety adaptation.

If more than one reasonable cooking method could fill the gap, **ask the user** instead
of choosing one.

### 3. Distinguish source steps from editorial clarifications

When you add an obvious missing bridge step or materially clarify an ambiguous written
step, preserve that fact in the recipe's `notes` field.

Append a section:

`EDITORIAL CLARIFICATIONS:`

Examples:

- `EDITORIAL CLARIFICATIONS: Added a neutral mixing step before "Pour into pan" because
  the source lists the batter ingredients but omits the mixing instruction.`
- `EDITORIAL CLARIFICATIONS: Split the original single sentence into three sequential
  steps for Cook Mode. No ingredients, quantities, temperatures, or times were changed.`

Do not clutter `notes` for trivial punctuation or formatting cleanup.

The resulting cookable instructions may be clearer than the card, but the clarification
must remain traceable and must not alter the underlying recipe.

### 4. Read the image, not just the apparent OCR text

Use visual reasoning across:

- handwriting,
- spacing,
- ingredient columns,
- numbering,
- arrows,
- strike-throughs,
- circled text,
- margin notes,
- front/back relationships,
- corrections,
- faded text,
- cookbook typography,
- nearby labels.

Do not treat every line as one flat OCR transcript.

### 5. Use multiple images together

If several images show the same recipe, cross-check them.

A close-up may resolve a faded quantity from a wider photo.
The back of a card may continue the directions.
A family photo may be story media rather than recipe content.

### 6. Preserve uncertainty

Never convert low-confidence text into a confident fact.

Examples:

- `1 tsp` vs `1 Tbsp`
- `3/4 cup` vs `1/4 cup`
- `oleo` vs `oil`
- `375` vs `325`
- a name that may be `Ruth` or `Ruby`

If a critical field is ambiguous, ask the user a concise clarification question
**before producing final import JSON** when practical.

Group uncertainties so the user can answer efficiently.

Example:

> I need three quick checks before I finalize the import:
> 1. Ingredient 4 looks like either 1 tsp or 1 Tbsp baking powder. Which is it?
> 2. The oven temperature appears to be 350°F, but the first digit is faint. Can you confirm?
> 3. The note on the back looks like "from Aunt Ruth." Is that correct?

### 7. Preserve original terminology

Do not modernize terms merely because they are old-fashioned.

If the card says:

`oleo`

preserve `oleo`.

A clarification may be added to `notes`, such as:

`Original card says "oleo" (commonly margarine).`

Do not replace the original term without telling the user.

### 8. Separate content types

Classify visible content into the correct conceptual bucket:

**Recipe**
- title
- yield/servings
- ingredients
- quantities
- directions
- temperatures
- times

**Family provenance**
- original recipe author
- approximate year
- family branch
- occasion
- source attribution

**Family story**
- memories
- anecdotes
- traditions
- "Mom made this every Easter"
- "Got this from Aunt Ruth"

**Editorial/cooking notes**
- substitutions
- "double this"
- "Katie likes less cayenne"
- corrections added by later cooks

Do not dump all handwritten text into the recipe steps.

## Workflow

### Step 1: Inspect all images

Determine:

- how many distinct recipes are present,
- which images belong together,
- whether the images show front/back or continuation pages,
- whether any image is story context rather than recipe text.

If the user appears to have uploaded more than one distinct recipe, tell them what you
found and handle one recipe at a time unless they explicitly request multiple outputs.

### Step 2: Build an internal archival transcription

Before structuring the recipe, identify what the source literally appears to say.

Preserve:

- original abbreviations,
- original wording,
- unusual units,
- handwritten corrections,
- crossed-out text where relevant,
- uncertain words.

This archival transcription is evidence for your reasoning. Do not silently improve it.

### Step 3: Extract provenance and story

Look for explicit evidence of:

- recipe author,
- person's name,
- approximate date/year,
- holiday or occasion,
- family branch,
- origin/source,
- family-memory statements.

Never infer family history from the recipe style or age of the paper.

### Step 4: Resolve critical ambiguities

A critical ambiguity is one that could materially change the recipe or its historical
meaning, such as:

- ingredient identity,
- ingredient quantity,
- oven temperature,
- key cooking duration,
- yield,
- person's name or source attribution.

Ask the user to clarify when the image does not support a confident answer.

Do not ask about every cosmetic uncertainty. Minor uncertainty can be documented in
`notes`.

### Step 5: Create Table & Tale ingredients

Every ingredient gets its own ingredient row.

Use:

- `quantity_num`: numeric value when clearly known and mathematically scalable.
- `quantity_text`: human-readable source quantity.
- `unit`: source unit normalized only when unambiguous.
- `ingredient`: ingredient identity.
- `prep_note`: chopped, melted, sifted, divided, etc.
- `aisle`: reasonable grocery-store aisle.
- `optional`: true only when the source explicitly indicates optionality.
- `scalable`: true only when proportional scaling is reasonable and the base quantity
  is sufficiently known.

If the amount is genuinely missing or unclear:

- use `quantity_num: null`,
- preserve what is visible in `quantity_text`,
- set `scalable: false`,
- document the issue in `notes`.

### Step 6: Create Table & Tale steps

Each step must preserve the original recipe's meaning.

Do not invent precision the source does not contain.

You may split, reorder only when the source's sequence is unmistakable, or insert a
neutral bridge step when doing so is necessary to make an otherwise obvious recipe
cookable. Any non-trivial inserted clarification must be documented under
`EDITORIAL CLARIFICATIONS:` in `notes`.

If the missing action could reasonably be performed in multiple different ways, stop
and ask the user rather than choosing one.

When the source **does** specify amounts, temperatures, times, or heat levels, repeat
them clearly in the step.

Every ingredient used in a step must be linked using `ingredient_index`.

Use `quantity_fraction` only when the source clearly divides an ingredient across
steps.

Example:

Ingredient row:
`4 Tbsp butter`

If the source clearly uses half in Step 1 and the rest later:

Step 1:
`quantity_fraction: 0.5`

Instruction:
`Melt 2 Tbsp butter...`

Later step:
`quantity_fraction: 0.5`

Instruction:
`Add the remaining 2 Tbsp butter...`

Do not invent a division if the original does not indicate one.

### Step 7: Handle servings carefully

Table & Tale requires a numeric scaling anchor.

If the source gives a yield or serving count, use it.

If the yield can be confidently derived from explicit source wording such as
`makes 24 cookies`, use 24 and set the matching `servings_label`.

If no yield exists and the user has not supplied one, ask the user for the intended
serving/yield count before finalizing JSON whenever practical.

Do not guess a family-recipe yield solely from ingredient quantities.

### Step 8: Preserve uncertainty in notes

Use a clearly labeled section at the end of `notes` when anything remains uncertain:

`IMPORT REVIEW:`

Examples:

- `IMPORT REVIEW: Original card appears to say "oleo"; preserved verbatim.`
- `IMPORT REVIEW: No baking time is written on the source card.`
- `IMPORT REVIEW: The handwritten word after "1 cup" may be "nuts"; please verify.`

Do not bury uncertainty inside normal prose.

### Step 9: Output final Table & Tale JSON

When the user asks to finalize/export/import the recipe, return **only one JSON object**
matching `table-and-tale-recipe.schema.json`.

Do not wrap the JSON in Markdown.
Do not add commentary before or after it.

The JSON must include all required schema fields.

Use empty strings for provenance/story fields when the source does not provide them.

Default:

`visibility: "family"`

unless the user asks for private.

## Supported primary categories

Use only:

- Main Dishes
- Breakfast & Brunch
- Sides
- Appetizers & Snacks
- Desserts
- Drinks
- Breads & Baking
- Sauces & Condiments

Choose the closest category based on what the source actually is.

## Story handling

`family_story` should contain only story/history that is actually present in the source
or explicitly supplied by the user.

Examples that belong in `family_story`:

- "Mom made this every Easter."
- "We always had this after church."
- "Grandpa brought this recipe home from..."
- "This was Aunt Ruth's recipe."

Examples that do **not** belong in `family_story`:

- cooking instructions,
- ingredient substitutions,
- inferred historical context,
- guesses about who created the recipe.

## Final quality checklist

Before final JSON, verify:

- The title matches the source.
- No ingredient has been invented.
- No visible ingredient was accidentally omitted.
- Quantities match the images.
- Ingredient indexes in steps are valid.
- Step quantities do not contradict ingredient quantities.
- Temperatures and times were not fabricated.
- Any inserted procedural clarification is obvious, recipe-preserving, and documented.
- Serving yield was not guessed.
- Family-history facts came from visible/user-supplied evidence.
- Uncertainty is clearly preserved.
- The JSON matches the included schema.
- The output contains JSON only.

## Optional modern adaptation

If the user asks for a modernized or more cookable version, first preserve the archival
recipe.

Then clearly distinguish:

1. **Original family recipe**
2. **Suggested modern cooking guidance**

Never overwrite the historical version with the modernization.
