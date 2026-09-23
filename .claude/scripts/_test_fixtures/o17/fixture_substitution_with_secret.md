# Fixture: substitution table with a planted dummy credential

This fixture is the CHECK (d) fail branch. It imitates a substitution table
that wrongly embedded a live credential value. The value below is a planted
dummy (prefix O17-DUMMY-), never a real secret.

```json
{
  "tokens": {
    "interpreter-path": {
      "live_value": "O17-DUMMY-CREDENTIAL-VALUE-1",
      "replacement_rule": "this row wrongly carries a credential value instead of a path"
    }
  }
}
```
