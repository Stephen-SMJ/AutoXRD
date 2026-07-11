# Coordinator Mode

> This feature exists in the official Claude Code codebase but has not been fully released. autoxrd implements and ships it.

Coordinator mode turns the assistant into an orchestrator that can launch background workers for parallel research, implementation, and verification.

## Usage

```bash
autoxrd --coordinator
# or
export AUTOXRD_COORDINATOR=1
autoxrd
```

## What It Adds

- **Background workers** — launch a worker and keep talking while it runs
- **Continuation flow** — continue a completed worker with more instructions
- **Task notifications** — worker results injected back as `<task-notification>` messages
- **Session-aware resume** — resumed sessions restore coordinator mode automatically

## Worker Tools

| Tool | Purpose |
|------|---------|
| `Agent` | Spawn a background worker |
| `SendMessage` | Continue an existing worker by task ID |
| `TaskStop` | Stop a running worker |

## Typical Workflow

1. Start `autoxrd --coordinator`
2. Ask for a larger task (research, implement, verify)
3. Coordinator launches workers in background
4. Worker results arrive as `<task-notification>` messages
5. Coordinator synthesizes results and decides next step

Workers use the standard tools: `Read`, `Glob`, `Grep`, `Edit`, `Write`, `Bash`.
