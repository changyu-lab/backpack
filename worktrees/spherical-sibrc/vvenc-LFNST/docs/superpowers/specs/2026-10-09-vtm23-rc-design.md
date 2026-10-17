# VTM-23.0 RC compatibility layer design

Date: 2026-10-09
Status: approved by user; implemented and reviewed. Official VTM provenance remains unverified (see provenance.json).

## Isolation and provenance

Development branch: codex/vtm23-rc-anchor.
VVenC anchor: official local tag v1.12.0, commit e9fa71223a3ffc2b35ed4026aea9cde1886cf6a9,
imported from I:/001-IBRC-exps/external/vvenc without its working-tree changes.
The parent repository initial commit contains IEPR changes and is excluded.
VTM candidate: I:/001-IBRC-exps/VTM-23.0-anchor-clean.
Its version.h declares 23.0; before extraction, verify RateCtrl.cpp/.h against
an official VTM-23.0 source and record upstream revision and SHA-256 hashes.
A directory name and version macro alone do not establish pristine provenance.
All source, builds, traces, test clips and reports remain in this isolated worktree.

## Selected architecture and alternatives

Extract the verified VTM controller with minimal dependency substitutions and
preserved license notices into source/Lib/EncoderLib/VtmRcCompat/.
Expose VtmRcSeq, VtmRcGOP, VtmRcPic, and VtmRcCtuState through a thin adapter.
Keep a mechanical symbol mapping so exported names do not obscure source origin.
Preserve VTM arithmetic, rounding, clipping, initialization, GOP hierarchy,
IRAP handling, picture history, and parameter update order.

Alternative 1: reimplement the published R-lambda equations. Rejected because
matching equations does not establish equivalence to VTM-23.0 implementation.
Alternative 2: parallel CTU scheduling with delayed feedback. Deferred because
it changes the controller state visible to the next CTU.

## Adapter and deterministic execution

Add an opt-in VTM RC selection and a dedicated target-bitrate setting, leaving
native RC code and default behavior intact. Native RC and compatibility RC are
mutually exclusive. Validate the effective configuration after preset expansion.
Require QPA off, native RC off, one encoding worker, no WPP, no frame parallelism,
one tile, and no competing CTU QP/lambda adaptation. Reject conflicting settings
with a precise error. Audit lookahead and temporal-filter scheduling separately;
one worker alone is not proof of controller serialization.

At picture start, construct VTM Seq/GOP/Pic budgets using actual VVenC GOP and
picture metadata. For CTU k, obtain target bits, lambda and QP from VTM, apply them
to VVenC coding and quantization, encode the CTU, collect VTM-compatible feedback,
and update the controller before issuing any decision for CTU k+1.
Use a dedicated CABAC estimator pass on the completed coding tree with maintained
contexts if VVenC search counters do not match VTM feedback semantics.
VTM EncSlice uses integer getEstFracBits() >> SCALE_BITS for CTU feedback.
Do not substitute final byte-stream deltas or accumulated search-cost counters.
Record CTU feedback bits and final picture coded bits as separate fields.
Picture/GOP/sequence updates must mirror VTM call-site semantics, including header
bits, skip ratio, effective pixels, average QP/lambda, and IRAP update flags.
The first implementation exposes a baseline redistribution seam but does not
implement I_eff redistribution or mix it into anchor validation.

## Trace and validation

First build the untouched official VVenC anchor and record toolchain and results.
Compile an independent reference harness against original verified VTM sources
and a compatibility harness against extracted sources. Run both with identical
scripted inputs and independently generated reference traces. Cover IRAP/inter,
GOP boundaries, partial CTUs, low budgets, clipping, and CTU model update modes.
Check integer fields exactly and doubles with an explicit documented tolerance;
start at abs=1e-12 and rel=1e-10 and explain any required relaxation.
Compare CTU target bits, QP, lambda, alpha, beta, and remaining budgets, plus
sequence/GOP/picture state. Include feedback-order assertions and divergence
reports. Comparing two copies of the same adapted kernel is insufficient.

Then run deterministic VVenC closed-loop tests at four ordered target bitrates
on a documented clip with enough frames to exercise budget adaptation. Confirm
decodability, repeated-run determinism, feedback completion before next decision,
picture and sequence accounting, bitrate error, QP/lambda distribution, and
absence of unbounded budget drift. Report bitrate error and RD monotonicity;
a tiny smoke clip alone cannot establish convergence. Real VVenC and VTM CTU
outputs need not match because coding engines differ.

## Acceptance and reporting

Call the result reproduced VTM-23.0 RC logic only after independent kernel replay
passes. Report closed-loop integration separately with actual measurements.
Do not claim convergence, RD monotonicity or buffer compliance without evidence.
If HRD/CPB control is enabled, port and test its associated VTM configuration and
updates explicitly; otherwise document HRD/CPB as outside the validated scope.
