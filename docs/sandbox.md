# Sandbox

> This feature exists in the official Claude Code codebase but has not been fully released. autoxrd implements and ships it.

Runs Bash commands inside [bubblewrap (bwrap)](https://github.com/containers/bubblewrap) isolation on Linux.

## How It Works

- Filesystem mounted **read-only** (`--ro-bind / /`)
- Only current working directory is **writable** (`--bind $CWD $CWD`)
- Network **isolated** by default (`--unshare-net`)
- Config files protected from modification
- PID namespace isolated (`--unshare-pid`)

## Modes

| Mode | Behavior |
|------|----------|
| `auto-allow` | Sandbox on, bash auto-approved |
| `regular` | Sandbox on, bash needs confirmation |
| `disabled` | No sandbox (default) |

## REPL Commands

```
> /sandbox                     # interactive mode selector
> /sandbox status              # show status + dependency check
> /sandbox mode auto-allow     # enable with auto-allow
> /sandbox mode disabled       # disable
> /sandbox exclude "docker *"  # skip sandbox for matching commands
```

## TOML Config

```toml
[sandbox]
enabled = true
auto_allow_bash = true
excluded_commands = ["docker *", "npm run *"]
unshare_net = true

[sandbox.filesystem]
allow_write = ["."]
```

## Excluded Commands

Patterns: exact (`"git"`), prefix (`"npm run"`), wildcard (`"docker *"`).
Excluded commands still need normal permission prompt.

## Graceful Degradation

If bwrap is not installed (non-Linux, Docker), sandbox auto-disables. Check with `/sandbox status`.
