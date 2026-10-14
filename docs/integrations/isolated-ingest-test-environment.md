# Isolated owned-architecture ingestion regression runner

Use `tests/run_owned_architecture_ingest.py` for the synthetic ingestion suite rather than launching `unittest discover` directly. The runner makes toolchain prerequisites explicit and keeps test data isolated.

```sh
/path/to/miniconda/bin/python3.12 tests/run_owned_architecture_ingest.py
```

Git resolution checks an explicit absolute `MNEMOSYNE_TEST_GIT` override, then executable `git` on PATH, then a sibling `git` next to the chosen Python executable (for Miniconda installs). It validates `git --version` before running a test. If Git is unavailable, the runner exits `2` with `TEST_ENVIRONMENT_ERROR`; it does not report a Mnemosyne application or memory-bank failure.

The runner prepends the chosen Git directory to the isolated subprocess PATH, disables embeddings and remote-embedding API usage, sets temporary `MNEMOSYNE_DATA_DIR` and `HERMES_HOME`, and clears system Git configuration for the subprocess. Temporary test data are deleted on exit. It does not change global PATH, runtime wrappers, deployed releases, production memory databases, or ingestion/sync activation flags.

The test suite still creates synthetic repositories in temporary directories. Do not interpret a successful test-runner result as permission to enable live ingestion or cross-device sync.
