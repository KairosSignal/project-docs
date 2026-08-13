# Demo Project Map

Read the backend index for authentication and billing work.

[Backend documentation](docs/backend-index.md)

```project-docs-index
{
  "schema_version": 2,
  "id": "demo-project-entry",
  "authority_key": "demo.project.entry",
  "level": 0,
  "role": "project_entry",
  "lifecycle_status": "active",
  "startup": [
    "docs/backend-index.md"
  ],
  "startup_budget": {
    "max_files": 3,
    "max_characters": 8000
  },
  "children": [
    {
      "id": "demo-backend-index",
      "path": "docs/backend-index.md",
      "propagation": "summary"
    }
  ],
  "archive_roots": [
    "docs/archive"
  ]
}
```
