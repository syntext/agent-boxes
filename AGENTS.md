# Development

Run Python 3.11 or newer. Keep the host CLI standard-library-only.

Read `registry.json` and `runtime.json` before changing app lifecycle behavior. Keep image-specific details, device requirements, and application lifecycle hooks in the registry or the relevant child directory. Keep upstream entrypoints and services intact.

Keep this file and the root README box-agnostic. Discover types through `registry.json` instead of listing the current catalog. Put application requirements, setup, and specialized commands in each type's README and skill. Use a selected registry key in shared command examples.

Use argument lists for subprocesses. Do not add shell evaluation. Treat state files as private because they include credentials. Never print them in status, logs, tests, or review output.

Keep each instance's writes under its own file lock. Use atomic replacement for saved configuration. Do not introduce a global mutable instance registry. Retain data by default.

Run `python3 -m unittest discover -s tests -v`. Run `scripts/verify.py` for changes that affect Docker, ports, mounting, authentication, desktop input, or device control. Use its unique test projects. The verifier covers its implemented fixtures, not every possible registry entry. Do not touch sibling projects or existing legacy containers.

Store large artifacts, downloads, and image caches under `~/work/boxes`. Do not commit runtime state, passwords, screenshots, or `.audit` artifacts. Do not automatically install global skill links.
