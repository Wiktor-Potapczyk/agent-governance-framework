---
date: <% tp.date.now("YYYY-MM-DD") %>
type: meta
tags: [moc, area, unclassified-pending]
status: active
---
# Area — <% tp.file.title %>

> Live dashboard. Do not edit query block.

```dataview
TABLE status, date
FROM "Areas/AREA_NAME_HERE"
WHERE status != "archived"
SORT date DESC
```
