# Beta 4 source sync and JSON import follow-up

The repository now includes the installed 3.3.0-beta.4 application, recipe skills,
local AI setup scripts, and Ollama model definitions. Runtime configuration,
databases, uploads, logs, backups, and virtual environments are excluded.

The installed VERSION file was stale (beta.2); the running application identified
itself as beta.4. The repository VERSION reflects the running application.

The JSON follow-up updates both skills to use a copyable JSON code block, explicitly
escape quoted text, and offer a validated file when tools are available. Import
errors now explain how to copy correctly. Existing comment/trailing-comma cleanup
preserves punctuation inside strings and reports a review warning. Serialized JSON
strings are decoded before object extraction. Ambiguous missing quotes or commas
are rejected rather than silently changing family recipe text.

Run focused regression tests with:

```powershell
python -B -m unittest discover -s tests -v
```

The legacy installer/windows scripts remain the original v3.2.2 packaging scripts;
this source sync is not a newly built Windows installer. Do not use that old updater
to deploy beta 4. Its payload and version checks require a separate packaging update.

To update the recipe skill already used in ChatGPT, replace its uploaded SKILL.md
and schema with the new repository copies or the downloadable Archivist skill ZIP.
An existing chat may still have the earlier instructions; supply the updated skill
when continuing that chat.
