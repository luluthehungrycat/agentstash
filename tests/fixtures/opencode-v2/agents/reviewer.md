---
description: Reviews code without modifying files
mode: subagent
model: openai/gpt-5
permissions:
  - action: shell
    resource: "*"
    effect: ask
  - action: "*"
    resource: "*"
    effect: deny
hidden: false
color: "#336699"
---
Review the requested changes. Report only findings supported by the repository.
