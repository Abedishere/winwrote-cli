---
name: win-cli
description: Control native Windows desktop apps (Explorer, Settings, Calculator, Office, WinForms/Win32/UWP apps, installers, dialogs) from the shell with the `win` CLI over UI Automation. Use for ANY desktop app task before windows-mcp. Text-only, runs in the background without taking the mouse or focus, so the user keeps using the PC. For web pages use the `web` CLI (web-cli skill) instead.
---

# win CLI

`win` is on PATH (PowerShell and Git Bash). Full reference: `~/Desktop/claude/winwrote-cli/README.md`.

## Loop

1. `win list` to find the window. `<win>` can be its `w<id>`, part of the title, or the exe name.
2. `win tree <win> -i` gives refs only; plain `win tree <win>` includes text too. Big windows: `--region <ref>`.
3. Act: `win click c12`, `win type c4 "text" [--clear|--append] [--enter]`, `win select c7 "Option"`.
4. Check the result: `win find <win> <text>` or `win wait <win> <text>`. Don't re-dump the whole tree.
5. Batch known steps: `win do` with commands on stdin, one per line.

## Rules

- Everything runs in the background by default. Only add `--real` (real mouse/keyboard, takes focus) after a background action fails, and tell the user it will grab their screen.
- `(app grabbed focus, handed back)` in the output is fine: the guard already restored the user's window.
- Minimized UWP apps (Calculator, Settings, new Notepad) have no controls. Run `win restore <win>` first; it doesn't activate the window.
- `stale ref`: the app rebuilt that control, so run `find` or `tree` again.
- `win shot <win>` prints a PNG path. Read it only if visuals actually matter.
- Never close or type into windows the user didn't ask about. Save prompts appear as new controls: `win tree` after `close`.
- Broken? `win selftest` should print `selftest ok`.
