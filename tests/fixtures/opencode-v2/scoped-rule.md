---
description: Has a path-specific restriction
mode: subagent
permissions:
  - action: read
    resource: "secrets/**"
    effect: deny
---
Inspect only permitted files.
