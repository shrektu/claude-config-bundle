---
name: datasheet
description: Load when a plan or diff relies on register, bit, offset, reset-value, timing, pin/AF or electrical-limit facts; checks them against the datasheet or reference-manual PDF via Argon (`agy_datasheet_check`).
---

1. PDF: a path from Sebastian, or a public URL downloaded only after his explicit OK, into a new empty
   directory.
2. List atomic numbered claims, one fact each (part, peripheral, register, offset, bit field, reset value,
   timing with unit and condition, pin/AF, voltage or current limit); at most ~40 per call.
3. Large manual: find the section's pages with
   `pdftotext -layout <pdf> - | awk -v RS='\f' 'tolower($0) ~ /<phrase>/ {print NR}'` and pass
   `first_page`/`last_page`.
4. Call `mcp__agy-worker__agy_datasheet_check` (`pdf_path`, `claims`, `context`, `first_page`,
   `last_page`; default model).
5. Check every REFUTED, UNCERTAIN and INVALID CITATION claim yourself on the cited page
   (`pdftotext -f N -l N -layout <pdf> -`); only then is it a finding.
6. MISSING VERDICT → ask again for those numbers only.
7. `AGY-UNAVAILABLE` → say why and check the critical claims yourself with `pdftotext`.
8. Report a table: claim → verdict → page → action.
