---
name: datasheet
description: Check claims from a plan or diff against a datasheet / reference manual PDF through Argon (agy-worker). Load when a plan or code relies on registers, bits, offsets, reset values, timings, pins and alternate functions or electrical limits that must be confirmed in the chip documentation.
---

## Steps

1. Get the PDF: a path from Sebastian or a public URL — download it only after his explicit OK,
   into your own new, empty directory.
2. List atomic, numbered claims from the plan or diff, one fact per claim: part number,
   peripheral, register name, offset, bit field, reset value, timing with unit and condition,
   pin/AF, voltage or current limit. At most ~40 per call.
3. For large manuals find the pages of the section with
   `pdftotext -layout <pdf> - | awk -v RS='\f' 'tolower($0) ~ /<phrase>/ {print NR}'` and pass
   `first_page` / `last_page`.
4. Call `mcp__agy-worker__agy_datasheet_check` (`pdf_path`, `claims`, `context`, `first_page`,
   `last_page`; default model, i.e. Argon). Page numbers in the result are physical PDF pages; the
   number printed on the page may differ.
5. Adjudicate: check every REFUTED, UNCERTAIN and INVALID CITATION claim yourself on the cited
   page: `pdftotext -f N -l N -layout <pdf> -`. Only then does it become a finding. Argon's verdicts
   are input, not orders.
6. MISSING VERDICT → ask again only for those numbers.
7. Report a table: claim → verdict → page → action.
8. `AGY-UNAVAILABLE` → say why, and check the critical claims yourself with `pdftotext`.
