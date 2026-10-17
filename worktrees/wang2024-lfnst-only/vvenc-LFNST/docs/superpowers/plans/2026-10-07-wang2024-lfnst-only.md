# Wang2024 LFNST-only implementation plan

User approved implementation and remote launch on 2026-10-07. Execute inline,
with independent review before formal launch. Follow test-driven-development
and verification-before-completion.

Goal: port the paper's printed kernel-specific rules and launch the matched
remote ERP matrix, without altering existing experiments.

Architecture: a header-only pure gradient/predicate helper in CommonLib;
off/shadow/on process configuration; evaluate at the primary-transform output
before LFNST and quantization. TrQuant exposes a per-call rejection flag.
IntraSearch treats rejected candidates as invalid, preserving native state
restoration and ISP early termination. Reuse the formal matrix9 evaluator
with paired environment selection and repeat1.

Tech stack: C++11, CMake Release, Python3, existing 360Lib evaluation and SSH.

- [x] Attach the independent worktree to codex/wang2024-lfnst-only; import
  `backups/Stage123_AI_WrongSkip_20261005/src` source/include/config baseline;
  record original source hashes. Copy approved spec into the worktree.
- [x] Create `tests/wang2024_predicate.cpp`. Compile before creating the helper
  and confirm missing-header failure. Test zero borders, rectangular stride,
  full TU border scope, inclusive flatness100, independent kernel thresholds,
  standard QPstep examples, and wide integer differences.
- [x] Create `source/Lib/CommonLib/WangLfnst.h`: `gradient(coeff,w,h,stride)`,
  `qpStep(qp)`, `skip(grad,index,qp)`, cached process mode and optional bounded
  aggregate audit. Run standalone tests to PASS.
- [x] Modify TrQuant.h/cpp: clear rejection every transform call; in luma
  nonzero-LFNST DCT-II candidates compute gradients from current tempCoeff
  after xT/loadTr and before xFwdLfnst; if on and rejected set flag and return.
  Shadow records predicates without pruning. No chroma pruning or forced zero
  CBF. Malformed mode must fail clearly.
- [x] Modify IntraSearch.cpp: after transformNxN in xIntraCodingTUBlock return
  invalid distortion when rejected; non-ISP transform loop continues before
  rate/reconstruction evaluation; ISP uses existing invalid-cost early exit.
  Confirm best-mode state restoration after skipped last candidate.
- [x] Build Linux Release off baseline and modified encoder. Run off/original
  and shadow/off bitstream+reconstruction hash checks on synthetic and real
  inputs; on must skip candidates and produce valid quality evaluation.
- [x] Add `tools/wang2024` matched matrix driver and manifest. Test option
  construction: 14x3x3x4x2=1008 encodes, AI1/RA16/LDP16, threads1, repeats1,
  GOP1/16/8, inherited native options, custom Stage pruning disabled.
  Use separate process env per arm; quality metrics precede REC deletion.
- [x] Request independent review of predicate, hook, candidate restore, and
  matched remote runner. Fix substantive findings and rerun affected checks.
- [x] Preflight authorized remote host, input14, converter/sphere, free disk,
  free physical CPU affinity and running experiments; never stop other jobs.
  Upload source/runner with checksums, build in a new directory; run smoke,
  then launch durable resumable paired matrix. Verify live PID plus actual
  encoder command and initial manifest, not merely a submitted shell command.
- [x] Commit only verified task changes on independent branch. Report branch,
  remote path, PID, exact configuration, checks passed and actual run status.

Commands: `g++ -std=c++11 -Isource/Lib/CommonLib tests/wang2024_predicate.cpp
-o wang_predicate && ./wang_predicate` must print PASS. CMake build must exit0.
All smoke hash checks must explicitly assert equality; predicate-enabled audit
must show considered and skipped nonzero-LFNST candidates. Every complete
formal cell needs original command, timing, encoder and 360Lib logs.
