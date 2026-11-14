# SunSpec for Home Assistant - agent instructions

Custom integration (domain `sunspec`) that reads SunSpec devices over Modbus TCP
through `pysunspec2`. Upstream: CJNE/ha-sunspec. Read this before writing code.

**Core principle:** a small codebase that stays small. Minimal, KISS and DRY,
yet a proper fix: find the root cause and fix it in the right layer.

## Map

- `custom_components/sunspec/api.py` - `SunSpecApiClient`, the only code that
  talks to `pysunspec2`.
- `__init__.py` - setup, unload, migration, `SunSpecDataUpdateCoordinator`.
- `config_flow.py` - config and options flow.
- `entity.py` - `SunSpecEntity`, the base for every entity.
- `sensor.py` - `SunSpecSensor`, `SunSpecEnergySensor`.
- `tests/` - pytest with a mocked device (`tests/test_data/*.json`).
- `scripts/simulator.py` - serves a fixture over Modbus TCP on 127.0.0.1:5020.

## Workflow

1. Read the whole codebase the change touches and its callers. Reuse what
   exists; never add a parallel path.
2. Check `git blame`, PRs and issues before changing behaviour; it may be
   deliberate.
3. Reproduce before fixing. If you cannot, say so; never present a suspicion
   as a confirmed defect.
4. Make the smallest complete fix. No unrelated refactors, renames or cleanup;
   report other findings separately.
5. Facts, not guesses. Verify every external API against its docs or source:
   Home Assistant developer docs and core, `pysunspec2`, the SunSpec specs.
6. Test in a running Home Assistant against the simulator
   (`python scripts/simulator.py [fixture]`), through the UI with Playwright
   and the log. Say what was checked live and what only through mocks.
7. Review the final diff for reproducible defects; keep speculation apart.

## Code

- Only what is needed. No verbose comments or code, no new abstraction,
  dependency or option the change does not require. Never vendor a dependency.
- One implementation of each thing; delete code that can no longer run.
- Use Home Assistant's mechanisms the way current core does. Never copy a
  deprecated pattern or change process-wide state.
- The integration only reads. Writing to a device needs a maintainer decision.
- Comments explain a decision the code cannot show, as the code is now.
  History belongs in commits. No debug logging or leftover prints.
- Docs and PR bodies state only what the code does and what was verified.

## SunSpec

- The model definitions bundled with `pysunspec2` are the authority for point
  names, types, units and symbols. Handle what they contain; never copy them.
  The one exception is `custom_components/sunspec/models/`: SunSpec's 2015
  definitions of 801-803, which `pysunspec2` dropped and the E3DC S10 still
  serves. A model at a 2015 length is read with them.
- Unsupported points hold a "not implemented" value that `pysunspec2` reads as
  None. For accumulators that value is 0.
- Bitfields (event flags, alarms) can have several bits set at once; they are
  not enums.
- Percent points are 0-100, scaled by their scale factor. Power factor is
  signed (EEI convention).
- Model 122 `Tms` counts seconds from 2000-01-01 UTC, and reading its limit
  status bits clears them.
- Writable points change how the device behaves on the grid, and Modbus has no
  authentication. In the DER curve models (705-712) the first curve holds the
  active settings.

## Tests

- A test pins behaviour a user would notice and fails when it changes.
- One test per behaviour; more inputs are `pytest.mark.parametrize` rows.
  Extend an existing test before adding one.
- A guard test must fail without its guard.
- No tests of constants, log text or Home Assistant itself.

## Validation

- While developing: the focused tests and `pre-commit run --all-files`.
- Before every commit: also the full suite,
  `pytest --timeout=9 -n auto -p no:sugar tests`.
- Report what ran, what passed and what could not run.

## Git and PRs

- Never commit, push or open a PR unless asked.
- Branch from upstream `main` and open the PR against CJNE/ha-sunspec `main`.
- One clean commit per PR, complete enough to need no follow-up fix. Rebase on
  upstream `main` and rerun the full suite before updating a PR branch.
- PR: a sentence-case title, and a description that says what now happens and
  why, uses a table where it shows the change better, and ends with one
  sentence on what was verified. No summary or test plan headings, no tool
  attribution. The release notes quote the first paragraph of each pull
  request that changes the integration, so it says what users now see.
