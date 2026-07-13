# Changelog

## 0.1.0 - 2026-07-13

Initial release of the Pitch RTI setup toolkit.

### Included

- Python CLI for verification, setup, discovery, settings, status, preflight, probing, and installed-RTI proof.
- External installer drop and user-data roots that work from a checkout or an installed wheel without modifying the package payload.
- Native, WSL, and Docker route plumbing with deterministic route-scoped ports.
- Vendor Docker staging for the installed Pitch `samples/docker` workflow, including `pitch docker init`, `up`, `restart`, `smoke`, `ps`, `logs`, `inspect`, and `down`.
- HLA 4 Preview settings discovery and opt-in configuration.
- Two-federate chat smoke support with discovered Java and C++ sample variants when present.
- Artifact-only checksum manifests for downloaded installers and support files; repository documentation and source files are not included in that manifest.
- Ignored `artifacts/` and `.tmp/` locations for generated state, staged payloads, test scratch space, and logs.

### Verified Release Surface

The Windows native route was exercised against an already-installed Pitch RTI 5.5.10 Free runtime. The installed RTI proof and two-federate chat smoke passed, and the Python suite passed with 91 tests.

### Known Limitations

- Pitch vendor binaries, licensing, and license-server behavior are outside this repository and must be supplied by the user.
- WSL route discovery and command execution are implemented, but the supplied Linux runtime did not produce the expected live CRC listener during this release validation.
- Docker route wiring and vendor-context staging are covered by tests; a live vendor Docker CRC/Web View run is not claimed unless the required vendor payload and Docker/license environment are available.
- HLA 4 Preview is surfaced as a Pitch setting and profile option; this toolkit does not independently certify the preview protocol behavior.
