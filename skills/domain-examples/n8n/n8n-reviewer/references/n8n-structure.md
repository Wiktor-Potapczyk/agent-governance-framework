# n8n Workflow JSON Structure Reference

Quick reference for understanding n8n workflow export files. Use this when parsing workflow JSON.

## Top-Level Structure

```json
{
  "nodes": [...],        // Required: array of node objects
  "connections": {...},  // Required: object mapping node names to their output connections
  "pinData": {...},      // Optional: pinned test data for nodes
  "settings": {...},     // Optional: workflow-level settings (timezone, error workflow, etc.)
  "staticData": {...},   // Optional: persistent data across executions
  "meta": {...}          // Optional: workflow metadata (n8n version, instance ID)
}
```

## Node Object

Every node has this structure:

```json
{
  "parameters": {},           // Node-specific configuration
  "type": "n8n-nodes-base.code",  // Node type identifier
  "typeVersion": 2,           // Version of the node type
  "position": [x, y],        // Canvas position [x, y] in pixels
  "id": "uuid",              // Unique node ID
  "name": "Node Name",       // Display name (used in connections & expressions)

  // Optional fields:
  "credentials": {           // External service credentials
    "serviceType": {
      "id": "credential-id",
      "name": "Credential Display Name"
    }
  },
  "onError": "continueErrorOutput",  // Error handling: "stopWorkflow" | "continueRegularOutput" | "continueErrorOutput"
  "retryOnFail": true,       // Whether to retry on failure
  "waitBetweenTries": 5000,  // Milliseconds between retries
  "maxTries": 3,             // Maximum retry attempts
  "notesInFlow": true,       // Whether to show notes in the flow
  "notes": "Description",    // Node notes/description
  "disabled": false          // Whether the node is disabled
}
```

## Common Node Types

### Triggers
| Type | Description |
|------|-------------|
| `n8n-nodes-base.webhook` | HTTP webhook trigger |
| `n8n-nodes-base.scheduleTrigger` | Cron/interval trigger |
| `n8n-nodes-base.manualTrigger` | Manual execution trigger |
| `n8n-nodes-base.executeWorkflowTrigger` | Called by another workflow |

### Data Processing
| Type | Description |
|------|-------------|
| `n8n-nodes-base.code` | JavaScript/Python code execution |
| `n8n-nodes-base.set` | Set/modify field values |
| `n8n-nodes-base.splitOut` | Split array field into individual items |
| `n8n-nodes-base.merge` | Merge items from multiple inputs |
| `n8n-nodes-base.filter` | Filter items by condition |
| `n8n-nodes-base.sort` | Sort items |
| `n8n-nodes-base.removeDuplicates` | Deduplicate items |
| `n8n-nodes-base.aggregate` | Aggregate items |

### Routing
| Type | Description |
|------|-------------|
| `n8n-nodes-base.switch` | Route to different outputs based on conditions |
| `n8n-nodes-base.if` | Binary true/false routing |
| `n8n-nodes-base.noOp` | No operation — pass-through (visual connector) |
| `n8n-nodes-base.stopAndError` | Stop execution with error message |

### External Services
| Type | Description |
|------|-------------|
| `n8n-nodes-base.httpRequest` | Generic HTTP request |
| `n8n-nodes-base.googleSheets` | Google Sheets operations |
| `n8n-nodes-base.slack` | Slack messaging |
| `n8n-nodes-base.gmail` | Gmail operations |
| `n8n-nodes-base.postgres` | PostgreSQL database |
| `n8n-nodes-base.mysql` | MySQL database |

### Documentation
| Type | Description |
|------|-------------|
| `n8n-nodes-base.stickyNote` | Visual comment/documentation on canvas |

### Community/Third-Party Nodes
Third-party nodes use a different prefix pattern: `@vendor/n8n-nodes-name.nodeName`
Example: `@apify/n8n-nodes-apify.apify`

## Connections Object

Connections define data flow between nodes. The structure maps source node names to their output connections:

```json
{
  "connections": {
    "Source Node Name": {
      "main": [           // "main" is the connection type (almost always "main")
        [                 // First output (index 0)
          {
            "node": "Target Node Name",
            "type": "main",
            "index": 0    // Which input of the target node
          }
        ],
        [                 // Second output (index 1) — for Switch, IF nodes
          {
            "node": "Another Target",
            "type": "main",
            "index": 0
          }
        ]
      ]
    }
  }
}
```

**Key points:**
- Node names in connections must exactly match the `name` field on nodes
- The outer array index = output number (Switch nodes have multiple outputs)
- Each output can connect to multiple target nodes
- A node not appearing as a key in connections has no outgoing connections
- Trigger nodes and sticky notes typically only appear as sources (triggers) or not at all (sticky notes)

## Expression Syntax

n8n uses expressions to reference data from other nodes. These appear in parameter values:

```
={{ $json.fieldName }}                     // Current item's field
={{ $('Node Name').item.json.fieldName }}   // Specific node's output
={{ $('Node Name').first().json.field }}    // First item from a node
={{ $('Node Name').all() }}                 // All items from a node
={{ $now.format('MM/dd/yyyy') }}           // Current timestamp
={{ $input.item.json.field }}              // Current input item
```

When renaming nodes, all `$('Old Name')` references in expressions across the entire workflow must be updated to `$('New Name')`.

## Sticky Note Structure

Sticky notes are nodes with no connections. They're purely visual:

```json
{
  "parameters": {
    "content": "# Section Title\nDescription text with **markdown** support.",
    "height": 624,    // Height in pixels
    "width": 848,     // Width in pixels
    "color": 6        // Color: 1=blue, 2=green, 3=yellow, 4=red, 5=purple, 6=teal, 7=orange
  },
  "type": "n8n-nodes-base.stickyNote",
  "position": [x, y],
  "typeVersion": 1,
  "id": "uuid",
  "name": "Sticky Note"
}
```

Sticky note content supports Markdown: headings (#), bold (**), links, lists, etc.

## Code Node Parameters

Code nodes contain JavaScript (or Python) in the `jsCode` parameter:

```json
{
  "parameters": {
    "jsCode": "const items = $input.all();\n// processing...\nreturn items;",
    "mode": "runOnceForAllItems"  // or "runOnceForEachItem"
  }
}
```

The `mode` determines whether the code runs once with all items or once per item:
- `runOnceForAllItems`: `$input.all()` returns array, must return array
- `runOnceForEachItem`: `$input.item` gives single item, return single object

## Google Sheets Node Parameters

```json
{
  "parameters": {
    "operation": "read" | "update" | "append" | "delete",
    "documentId": { "__rl": true, "value": "sheet-id-or-expression", "mode": "id" },
    "sheetName": { "__rl": true, "value": "sheet-name-or-id", "mode": "id" },
    "columns": {
      "mappingMode": "defineBelow" | "autoMapInputData",
      "value": { "Column Name": "value or expression" },
      "matchingColumns": ["column-used-for-matching"]
    }
  }
}
```

## HTTP Request Node Parameters

```json
{
  "parameters": {
    "method": "GET" | "POST" | "PUT" | "DELETE" | "PATCH",
    "url": "https://api.example.com/endpoint",
    "authentication": "none" | "genericCredentialType" | "predefinedCredentialType",
    "sendHeaders": true,
    "headerParameters": { "parameters": [{ "name": "Header", "value": "value" }] },
    "sendBody": true,
    "bodyParameters": { "parameters": [{ "name": "field", "value": "value" }] }
  }
}
```
