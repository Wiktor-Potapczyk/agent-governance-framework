---
date: <% tp.date.now("YYYY-MM-DD") %>
type: meta
tags: [moc, portfolio, unclassified-pending]
status: active
---
# Project Portfolio

> Live dashboard. Do not edit query blocks.

## Active

```dataview
TABLE status, date
FROM "Projects"
WHERE type = "project-state" AND status = "active"
SORT date DESC
```

## Waiting / blocked

```dataview
TABLE status, date
FROM "Projects"
WHERE type = "project-state" AND status = "waiting"
SORT date DESC
```

## Completed

```dataview
TABLE date
FROM "Projects"
WHERE type = "project-state" AND status = "done"
SORT date DESC
```
