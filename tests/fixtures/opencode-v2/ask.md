---
description: Requests shell approval
mode: subagent
permissions:
  - action: "*"
    resource: "*"
    effect: deny
  - action: shell
    resource: "*"
    effect: ask
---
Ask before using shell.
