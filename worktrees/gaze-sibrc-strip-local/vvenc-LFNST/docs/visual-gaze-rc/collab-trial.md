# Gaze + frozen C4 development trial

`tools/visual_gaze/collab_trial.py` runs only DrivingInCity and DrivingInCountry,
32 actual coded frames with frozen RA32 / NumRefPics=1 commands. Each has four
original targets at alpha 0.10 and 0.25: sixteen formal hybrid encodes. The remote trial uses four workers with a 24 GB
reservation ceiling plus checks of actual available RAM and scratch space. These are
development sequences, not an independent holdout.

For each CTU the adapter computes
`mixed = round((1-alpha)*original + alpha*strip)` and then the frozen SIBRC C4
controller chooses final QP/lambda. The runner clones the complete old C4 command,
retains model/statistics/configuration/input arguments, redirects every output
trace and bitstream, and appends the collaboration and old frozen feature options.
It writes encoder reconstruction into its own temporary scratch directory.

## Invocation

Run on the remote host from the new source checkout (the runner itself never uses
SSH). Supply the already verified native decoder, metric executable and sphere:

```sh
python3 -u tools/visual_gaze/collab_trial.py \
  --encoder /root/gaze_sibrc_collab_20261016/src/bin/release-static/vvencFFapp \
  --reference /data/vtmrc-vvenc-ra32-20261014 \
  --strip-reference /root/visual_gaze_ra32f_matched_20261015/results \
  --decoder "$DECODER" --metric "$METRIC" --sphere "$SPHERE" \
  --output /root/gaze_sibrc_collab_20261016/results \
  --scratch-root /dev/shm/gaze_sibrc_collab_20261016 \
  --workers 2
```

All old input trees remain read-only. The output and scratch roots must be outside
the frozen reference trees. Existing jobs are never stopped or cleaned. The
runner reserves estimated concurrent memory against actual available RAM and
actual scratch free space; it can wait when other jobs use those resources.

## Required evidence

Before the formal ladder, four DrivingInCity R1 compatibility encodes must match
the frozen SHA256: both disabled versus Anchor; gaze alone versus old strip;
SIBRC alone versus C4; combined alpha zero versus C4. These are limited empirical
gates. Saved gate evidence is tied to the immutable experiment manifest, with
bitstream and compressed/raw trace identity checks on resume.

The runner verifies frozen Anchor/C4 run/quality records and output hashes,
all source prefixes, frozen feature content/header/metadata and coefficients,
model/statistics files, metric/sphere identities, target ladders and configuration.
No formal Anchor or CQP ladder is rerun.

Every formal point requires complete 32-frame I/B logs, unique full CTU geometry,
the blend equation, nonzero mixed-budget and SIBRC activity, fallback counts,
and `frame_before-frame_after=bits`. At alpha zero the gate additionally requires
`strip_target=-1` and exact original/mixed budget equality. Pure gaze debit
semantics are separately covered by the controller tests.

Each point runs `evaluate.py` for PSNR, WS-PSNR and S-PSNR-NN; it independently
decodes and compares the complete reconstruction hash; native metrics provide
CPP-PSNR and cross-check the exact S-PSNR convention across all 32 frames.
Successful raw traces become gzip files with both raw and compressed SHA256;
temporary raw reconstructions are discarded after these checks. Subprocess logs,
commands, metrics, bitstreams and per-point evidence remain independent.

`summary.json` contains all points, per-point quality/bitrate relative to C4,
per-sequence BD-rate versus Anchor and versus C4 for all four metrics, and equal
weight averages across both sequences for both alphas. Incomplete trials suppress
all complete averages; unavailable BD intervals are recorded with their reason.
No selective sequence exclusion or independent holdout claim is permitted.

## Resume and tests

Re-run the same invocation to resume. Changes to executable/code, frozen
dependencies or metadata refuse the manifest. Completed points recheck saved
bitstreams, command/log/metric artifacts and both compressed/raw trace hashes.
Use a new independent output directory when intentionally changing identity.

```sh
python3 -m unittest discover -s tools/visual_gaze -p test_collab_trial.py
```

Remote build and initial verification: 40 CTest cases and 26 Python tests passed.
After strengthening trace checks, all 11 runner tests passed locally and remotely.
Inactivity does not suppress metrics or BD-rate; it is reported as ineligible.
SIBRC fallback is retained as a diagnostic, since the frozen controller also uses
this path. It is not an added algorithmic rejection rule. Every formal point joins
VTM, SIBRC, gaze and collaboration traces; it checks actual feedback, QP/offset,
positive synchronized lambda, contiguous frame budgets and strip debits.
Historical frozen-assets.json is verified before reusing any reference.
