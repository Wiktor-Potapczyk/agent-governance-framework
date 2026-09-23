---
date: <% tp.date.now("YYYY-MM-DD") %>
type: meta
tags: [moc, topic, unclassified-pending]
status: active
---
# Topic — <% tp.file.title %>

> Live dashboard. Do not edit query block.

```dataview
LIST
FROM #CONCEPT_TAG_HERE
WHERE status != "archived"
SORT date DESC
```
