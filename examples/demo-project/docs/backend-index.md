# Backend Documentation

- [Authentication contract](auth-contract.md)
- [Billing contract](billing-contract.md)

```driftlock-index
{
  "schema_version": 2,
  "id": "demo-backend-index",
  "authority_key": "demo.backend.index",
  "level": 1,
  "role": "module_index",
  "lifecycle_status": "active",
  "read_when": {
    "any": [
      "the task changes authentication",
      "the task changes billing"
    ]
  },
  "children": [
    {
      "id": "demo-auth-contract",
      "path": "docs/auth-contract.md",
      "propagation": "summary"
    },
    {
      "id": "demo-billing-contract",
      "path": "docs/billing-contract.md",
      "propagation": "link_only"
    }
  ]
}
```
