# Matched experiment runner

Use Python 3.9+ (tested with the bundled primary runtime). `run_matched.py`
requires explicit encoder, trained model, ERP sequence directory, output root,
360Convert executable, sphere file, and reference-runner root. `--dry-run`
writes `plan.json` and prints all commands, intervention environments and hashes.

The reference root must contain the five unmodified files listed in
`reference_hashes.json`, in their original `tools/` hierarchy. It can be the
formal backup runner or a byte-identical independent snapshot. No old runner
files are modified or executed as a main program.

Defaults are AI, RA, LD; 1/32/16 frames; GOP 1/16/8; QPs 22,27,32,37;
two counterbalanced repeats; medium; 32 threads; qpa=0; mtprofile=0.
Both arms force `LFNST=1 LardLfnstSkip=0`. Only `SALDANHA_MODE` changes
from off to on; training CSV logging is removed from the inherited environment.
Run `--configs AI` first and `--configs RA,LD` subsequently if desired.

Completed cases resume automatically only after exact provenance and retained
artifact hashes validate. A changed model, executable, helper, or command is
rejected. Failed/incomplete case directories are preserved and rejected;
investigate them, then use a fresh output root. A crash may leave `runner.lock`;
remove that one file only after verifying the original process has stopped.
One runner serializes all encoder jobs; do not run other encoders concurrently.
Windows admission requires at least 8 GiB free memory, configurable with
`--min-free-gib`. Source identity records path, size and mtime, not a full YUV hash.

Bitstreams, logs, official metrics, and proposed intervention stats are retained.
Only runner-produced reconstructions are deleted, after successful metrics and
manifest validation. A complete set of paired repeats is required for summaries;
BD-rate further requires four valid QPs and overlapping quality intervals.
Timing reports repeat-level aggregate TS best and median, matching the legacy
helper. No Stage123 performance acceptance thresholds are applied.

Tests: `python test_runner.py`. Set `SALDANHA_REFERENCE_ROOT` to the pinned
snapshot location when moving the tests; the default is the original formal
backup at `I:/vvenc-LFNST/backups/S123AB_formal_20261005/runner`.
The sphere file in the current package is
`I:/vvenc-LFNST/dist/windows_s123ab_rdmax_package_20260811/360Lib/sphere_655362.txt`.
The persistent tiny `test_fixture` directory is
synthetic test data, not encoded results; no real encoder is launched by tests.
