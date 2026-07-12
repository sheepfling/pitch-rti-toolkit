# PITCH HLA Starter Files

This repo is a Python-first starter bundle for Pitch RTI / HLA setup on Linux and Windows.
It is organized as a conventional Python project with `src/` for implementation and `tests/` for smoke checks.
The downloaded vendor bundle lives under `pitch/`, including the SHA manifest used for verification.
It is intended to be cloned directly or added as a git submodule from a larger project.

## Quick Flow

`pitch` is the canonical entry point after installation. The `setup`, `verify`, `status`, `probe`, `doctor`, and `config` subcommands all share the same Python implementation.
`pitch preflight` gives you a cached readiness report for Docker, the bundle, the RTI launcher, and configured ports.

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
On WSL, the CLI also translates Windows-style paths like `C:\Users\you\Downloads\pitch` into the matching `/mnt/c/...` locations when you pass them on the command line or through the relevant environment variables.

To print the resolved paths:

```bash
pitch config assets
```

If you only have a folder of downloaded Pitch files, stage the recognized ones into the writable cache:

```bash
pitch assets import C:\\Users\\you\\Downloads\\pitch
```

The command recursively scans the folder for known Pitch installer and support files, then copies them into the cache root so you do not need to keep the original downloads folder around.

To stage a folder and run setup in one step:

```bash
python -m pitch setup --source C:\\Users\\you\\Downloads\\pitch
```

If you want to choose an execution route explicitly, use:

```bash
pitch route show
pitch route run native setup
pitch route run wsl setup
pitch route run --wsl-distro 1 wsl setup
pitch route run docker setup
pitch setup --route wsl
pitch setup --route wsl --wsl-distro Ubuntu
pitch setup --route docker
PITCH_DOCKER_PROFILE=hla4 pitch route run docker verify
```

`native` runs directly on the host OS, `wsl` runs the command through WSL on Windows, and `docker` runs it through Docker Compose in a Linux container.
On Windows, the CLI now recommends `native` by default and leaves `wsl` and `docker` as explicit opt-in routes.
`pitch route show` lists WSL distros with indexes, so `--wsl-distro 1` picks the first detected distro and `--wsl-distro Ubuntu` picks by name.
`pitch setup --route ...` uses the same route choices for the main install flow.

The Docker route keeps the mutable pieces outside the checkout:

- `PITCH_USER_DATA_ROOT` stores the container's install state and preflight artifacts.
- `PITCH_INSTALLER_DROP_ROOT` stores the installers users drop in for setup.
- `PITCH_DOCKER_PROFILE` selects the Compose service, with `future` as the default and `hla4` available when you want that track instead.
- `pitch docker init` writes a reusable Compose env file under the user data root, which the route picks up automatically.

The Compose assets live in `docker/compose.yml` and `docker/Dockerfile`.

For the official Pitch container path, the CLI now also understands the vendor `samples/docker` tree that ships with the installed RTI. That flow is meant for running the CRC itself in Docker, not for the generic repo helper container:

```bash
pitch docker init
pitch docker init --enable-hla4-preview
pitch docker status
pitch docker up
pitch docker restart
pitch docker smoke
pitch docker ps
pitch docker logs
pitch docker inspect
pitch docker down
```

`pitch docker init` copies the vendor `prti1516eCRC.settings` and `prti1516eLRC.settings` into a writable overlay under the user data root, stages the Docker build context into a separate writable folder, writes a separate `pitch-vendor-compose.env`, and keeps the original checkout or wheel untouched.
If you enable HLA 4 Preview, the copied CRC settings file is updated in place so the setting is discoverable before startup.
When Web View is enabled, `pitch docker up` and `pitch docker smoke` also probe the `http://127.0.0.1:8080/webview/` path after the RTI port is reachable.
`pitch docker restart` performs a stop/start cycle and reruns the smoke check, while `pitch docker inspect` prints the setup summary and then shows the Compose `ps --all` output for the vendor CRC container.
The vendor container Compose file lives at `docker/pitch-vendor-compose.yml` and uses the staged vendor build context created by `pitch docker init`.

To smoke-test the installed RTI, launch the console and ask it for help:

```bash
pitch start prti1516e
```

At the `pRTI>` prompt, type `HELP` to confirm the console is alive. Use `QUIT` to exit cleanly.
When the RTI target starts, the CLI now prints the discovered CRC settings summary first, including whether `CRC.enableHla4PreviewFeatures` is enabled.
To inspect the full discovered settings table without launching the RTI, run:

```bash
pitch settings show
```

You can also run the automated smoke test with `pitch rti smoke`.
To try two chat federates against the installed RTI, use:

```bash
pitch rti smoke chat
```

That command prefers the Java HLA 4 chat sample by default, but `pitch rti smoke chat --list` will show the discovered `java-hla4`, `java-hla4-fedpro`, and `cpp-hla4` variants when they are present.
To include that check in the normal verification flow, run `pitch verify --rti-smoke`.

## Pitch Free-Download Form

Pitch’s free-download page still expects a contact form to be filled out before the bundle is sent.
The helper now opens the current Pitch install page directly:

`https://www2.pitch.se/pRTI1516e/Releases/v5.5.10-free/SnvHLyNhR6A9ZgoQ/install.asp`

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

If Pitch gives you a direct file link and you want the CLI to fetch it, use:

```bash
python -m pitch download fetch --url https://example.com/pitch-download.bin --output C:\\Users\\you\\Downloads\\pitch-download.bin
```

If you have the Pitch install page instead of a direct file link, you can still pass that page URL and choose the installer by `--filename` or `--platform`.

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

If the vendor installers support unattended mode on your machine, try:

```bash
pitch setup --silent-install
```

On Linux and WSL, the same setup flow uses the `.sh` installers from `pitch/linux/` and the Linux launcher discovery path.

## Verification

`verify` confirms the bundle is complete before you install anything:

- required bootstrap files and payloads exist
- the port probe config is present

Downloaded installers and other staged vendor artifacts are verified separately with:

```bash
pitch assets verify
```

That command checks the local checksum manifest written into the installer drop root by `pitch assets import`.

## Layout

- `src/pitch/` - shared Python CLI package implementation
- `src/pitch_bootstrap.py` - shared bootstrap helpers
- `pyproject.toml` - packaging metadata and `pitch` console script entrypoint
- `tests/` - smoke tests for the Python workflow
- `pitch/docs/` - user guides and tutorials
- `pitch/plugin/` - Pitch Unreal Engine connector package
- `pitch/linux/`, `pitch/windows/`, and `pitch/mac/` - vendor payloads and unpacked runtime trees
- `pitch/ports.conf` - default port probe list
- `pitch/checksums.sha256` - bundle fingerprint marker for the source tree
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
4. Run `pitch preflight` to capture a readiness report, then `pitch status` to see install state, RTI smoke availability, and port readiness.
5. Run `pitch start <target> --probe-ports` to launch a target and check the port profile.
