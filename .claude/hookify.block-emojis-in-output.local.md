---
name: block-emojis-in-output
enabled: true
event: file
action: block
pattern: '[\U0001F300-\U0001FAFF☀-➿⬀-⯿️]'
---
EMOJI / DECORATIVE GLYPH DETECTED in content being written.

Wiktor's standing rule: no emojis and no decorative Unicode symbol markers (stars, check marks, gear, warning sign, cross mark, and the broader emoji blocks) in any prose or deliverable. Use plain words instead — "in / partial / out", "most-requested", "top pick".

Rewrite the content without the emoji/glyph, then write again. This matches new content only, so it will not block you from REMOVING an emoji (clean replacement text passes).

Reference: feedback_no_emojis_in_output. Pairs with the no-abbreviations rule.
