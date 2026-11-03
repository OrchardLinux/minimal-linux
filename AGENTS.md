# Notes for coding agents

Building, running, disk and device rules are orchard's; see orchard's
[AGENTS.md](https://github.com/OrchardLinux/orchard/blob/main/AGENTS.md).
In short: clean up what you made when you are done with it, check `df -h ~`
before large builds, don't delete what others made unless asked, and ring the DFU bell
when a person has to do something physical.

This image's build runs orchard's producers as commands and imports none of
orchard's Python (`snapshot.py`, `tests/test_no_orchard_imports.py`).
