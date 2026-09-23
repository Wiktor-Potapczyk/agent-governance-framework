---
date: <% tp.date.now("YYYY-MM-DD") %>
type: meta
tags: [moc]
status: active
---

# Index — <% tp.file.title %>

> Live dashboard. Do not edit query block.

```dataview
LIST
FROM #TAG_HERE
WHERE status != "archived"
SORT date DESC
```
