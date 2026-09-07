# Table & Tale Recipe Card Archivist

This package is for extracting existing family recipes from photos while preserving
the historical source.

Files:

- `SKILL.md` - the reusable Recipe Card Archivist workflow
- `table-and-tale-recipe.schema.json` - exact Table & Tale import structure
- `CHATGPT_FALLBACK_PROMPT.txt` - instructions for accounts without installable Skills

## ChatGPT Skills installation

On ChatGPT accounts/workspaces that support uploaded Skills:

1. Open **Plugins**.
2. Open the **Skills** tab.
3. Select **Create**.
4. Select **Upload from your computer**.
5. Upload this skill package.

After it is installed, upload recipe photos and ask:

`Archive these for Table & Tale.`

The skill should ask for clarification when critical handwriting is ambiguous and then
produce final Table & Tale JSON.

## Table & Tale import

Copy the final JSON into:

**Add Recipe -> AI Recipe JSON -> Validate & Import**

Always review the imported recipe before saving.

## Personal ChatGPT accounts

If your account does not show the Skills upload interface, use
`CHATGPT_FALLBACK_PROMPT.txt`. Upload `SKILL.md` and the schema directly into the chat
along with the recipe photos.

## Conservative procedural reconstruction

This revision allows the Archivist to add an obvious missing bridge step or split a
dense instruction into clearer Cook Mode steps when doing so does not change the
recipe. Any meaningful inserted clarification is recorded under
`EDITORIAL CLARIFICATIONS:` in the recipe notes.

If there is more than one plausible method, the skill asks the user instead of guessing.
