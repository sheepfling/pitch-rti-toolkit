# PITCH HLA Starter Files

This repo is a Python-first starter bundle for Pitch RTI / HLA setup on Linux and Windows.
It is organized as a conventional Python project with `src/` for implementation and `tests/` for smoke checks.
The downloaded vendor bundle lives under `pitch/`, including the SHA manifest used for verification.
It is intended to be cloned directly or added as a git submodule from a larger project.

## Quick Flow

`pitch` is the canonical entry point after installation. The `setup`, `verify`, `status`, `probe`, `doctor`, and `config` subcommands all share the same Python implementation.

For local development from a checkout, install the project in editable mode first:

```bash
python -m pip install -e .
```

Use this order for the common path:

```bash
pitch verify
pitch setup
pitch doctor
pitch status
pitch probe
pitch start hlastarterkit --port 1516 --probe-ports
```

If you prefer invoking the module directly, `python -m pitch` still works after installation. On Windows, prefix the same commands with `py -3` when using `python -m pitch`; on Linux, use `python3`.

`setup` checks for an existing install before launching anything. It uses a local state marker in the repo first, then falls back to platform checks:

- Windows: registry and install4j uninstall entries
- Linux: common install locations and launcher files

When `setup` needs an installer, it looks in the bundled `pitch/` tree first and then searches common user locations like `Downloads/` and cache folders.
If you install this as a wheel and keep the payload bundle elsewhere, set `PITCH_ASSET_ROOT` to that bundle directory before running `pitch`.

If auto-discovery is ambiguous, create a machine-local override file named `.pitch-install-roots.json` in the repo root. You can generate it with:

```bash
pitch config init
```

To inspect the detected roots or the override file:

```bash
pitch config show
```

## Writable Asset Location

The checked-in `pitch/` folder is the bundle namespace for docs, manifests, and checked-in helper files.
Installer binaries should live outside the repo or wheel in a user-writable asset directory.

By default, Pitch uses:

- Windows: `%LOCALAPPDATA%\pitch-rti-toolkit\installers`
- Linux: `~/.local/share/pitch-rti-toolkit/installers`
- macOS: `~/Library/Application Support/pitch-rti-toolkit/installers`

You can override that root with `PITCH_USER_DATA_ROOT`.
If you only want to change the installer folder, set `PITCH_INSTALLER_DROP_ROOT` instead.

To print the resolved paths:

```bash
pitch config assets
```

## Pitch Free-Download Form

Pitch’s free-download page still expects a contact form to be filled out before the bundle is sent.
To keep the contact details in one place, copy `pitch/download-contact.example.json` to `.pitch-download-contact.json` and update only the values you want to reuse.
Or let the CLI generate the local contact file from an email address:

```bash
python -m pitch download init --email you@example.com
```

The most important field is:

- `destination_email` - where Pitch should send the download information

The other fields in the template mirror the form defaults shown on the Pitch site, so new users can fill the form with less guesswork.
To generate a browser-side autofill helper for the live Pitch form:

```bash
python -m pitch download bookmarklet
```

That prints a `javascript:` bookmarklet that fills the form from `.pitch-download-contact.json`, leaving only the email address for the user to enter.
If the Pitch bundle is not present in `pitch/`, the command prints the manual form path instead of a bookmarklet.

For a plain browser script you can save or paste into DevTools:

```bash
python -m pitch download script
```

The checked-in version lives at `pitch/download-autofill.js`.
You can also seed the browser prompt default with `--email you@example.com`.
After filling the form, the script asks for confirmation and then clicks the submit button if one is present.

To submit the free-download request directly from Python instead of using the browser helper:

```bash
python -m pitch download submit --email you@example.com
```

That uses the same saved contact defaults and posts the request to Pitch's form endpoint.
Add `--dry-run` if you want to inspect the payload before sending it.

For a one-step install-and-probe run:

```bash
pitch setup --probe-ports
```

If you want the port probe to fail when any target is closed:

```bash
pitch probe --strict
pitch setup --probe-ports --strict-probe
```

To include the legacy 32-bit RTI package on Windows:

```bash
pitch setup --include-legacy-rti
```

To rerun the installers anyway:

```bash
pitch setup --force
```

## Verification

`verify` confirms the bundle is complete before you install anything:

- required bootstrap files and payloads exist
- SHA-256 checksums match `pitch/checksums.sha256` for vendor payloads and bundled PDFs
- the port probe config is present

## Layout

- `src/pitch/` - shared Python CLI package implementation
- `src/pitch_bootstrap.py` - shared bootstrap helpers
- `pyproject.toml` - packaging metadata and `pitch` console script entrypoint
- `tests/` - smoke tests for the Python workflow
- `pitch/docs/` - user guides and tutorials
- `pitch/plugin/` - Pitch Unreal Engine connector package
- `pitch/linux/`, `pitch/windows/`, and `pitch/mac/` - vendor payloads and unpacked runtime trees
- `pitch/ports.conf` - default port probe list
- `pitch/checksums.sha256` - vendor payload and PDF checksum manifest
- `pitch/pitch-install-roots.example.json` - sample machine-local install-root override
- No root-level shell, PowerShell, cmd, or Python compatibility shims are shipped

## Using as a submodule

From another repo:

```bash
git submodule add <this-repo-url> vendor/pitch-hla-starter-files
git submodule update --init --recursive
```

Then launch via the nested path, for example:

```bash
pitch setup --probe-ports
```

## Practical Order

1. Run `pitch verify` to confirm the bundle is intact.
2. Run `pitch setup` to install the core Pitch stack.
3. Run `pitch doctor` to inspect the Python workflow and detected install roots.
4. Run `pitch status` to see install state and port readiness.
5. Run `pitch start <target> --probe-ports` to launch a target and check the port profile.
