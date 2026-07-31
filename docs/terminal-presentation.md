# Terminal presentation

`imr-sqliblind` v0.8.1 provides a professional terminal theme shared by extraction, service, user-management, configuration, update, help, progress, and error output.

The interactive banner is:

```text
+--------------------------------------------------+
|               Blind SQL Injection                |
|                  imr-sqliblind                   |
|                  imr :: v0.8.1                   |
+--------------------------------------------------+
```

The version is read from the installed package, so it changes automatically in later releases.

## Color modes

```bash
sqliblind --color auto --help
sqliblind --color always status
sqliblind --color never map
sqliblind --no-color users list
```

- `auto` is the default. ANSI colors are enabled only for an interactive terminal.
- `always` forces ANSI colors, including when terminal detection is unavailable.
- `never` disables ANSI colors.
- `--no-color` is an alias for `--color never`.
- The standard `NO_COLOR` environment variable disables colors in automatic mode.
- `SQLIBLIND_COLOR=auto|always|never` sets a user-level default.

Terminal options are global and may be placed before or after a command:

```bash
sqliblind --color always status
sqliblind status --color always
```

## Banner control

The banner appears only in an interactive terminal. It is automatically omitted from redirected output, JSON, `config show`, internal service execution, and `--version`.

Disable it explicitly with:

```bash
sqliblind --no-banner --help
sqliblind status --no-banner
```

## Machine-readable output

ANSI codes and the banner are never added to machine-readable modes, even when `--color always` is supplied:

```bash
sqliblind --color always --json map > result.json
sqliblind --color always config show > service-config.json
sqliblind --color always map --format json > database-map.json
```

This keeps JSON valid and preserves compatibility with scripts, pipes, reports, and redirected output.

## Windows support

On Windows, automatic mode enables Virtual Terminal Processing only for the current console handle. It does not modify the registry, system-wide console settings, or user environment configuration.
