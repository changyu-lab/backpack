# Genuine WEKA REPTree training

Requires Java JDK 17, WEKA stable 3.8.6 and bounce 0.18. Python uses only its standard library. Dependencies may live outside the source checkout; do not commit the JDK or jars. Official Maven artifacts: `nz.ac.waikato.cms.weka:weka-stable:3.8.6`, `nz.ac.waikato.cms.weka.thirdparty:bounce:0.18`.

```powershell
python train.py --input training.csv --train-sequences Kimono ParkScene --validation-sequences OtherSequence --output trained --java PATH_TO_JDK/bin/java.exe --javac PATH_TO_JDK/bin/javac.exe --weka PATH_TO/weka.jar --extra-classpath PATH_TO/bounce.jar
python -m unittest -v test_train
$env:JAVA_HOME='PATH_TO_JDK'
python -m unittest -v test_integration
```

Input CSV has the thirteen feature columns in `train.FEATURES`, plus `sequence,poc,qp,label`. All features are numeric; extra metadata columns are accepted. Label 0 means nonzero LFNST does not improve RD cost, label 1 means it does. Entire Sequences360 and ERP14 paths/metadata are rejected. Train and validation must name explicit nonempty disjoint sequence sets. Unknown requested names, nonfinite features and invalid labels fail before training.

Training selects deterministic equal class pairs inside each sequence/POC/width/height/QP stratum, round-robin over sorted strata, capped at 20,000 rows by default. Strata lacking either class are omitted from training; validation retains all selected sequence rows. A seed of 2022 and depth limit of 8 are defaults; WEKA reduced-error pruning defaults remain enabled. The resulting node count is learned, never forced to 123.

Outputs include serialized genuine `weka.model`, `model.txt`, readable `weka_tree.txt`, selected training and full validation ARFFs, reference and independently inferred validation predictions, `equivalence.json`, and provenance `manifest.json` with file hashes and sequence split. Synthetic integration data is only a tooling test and is never a deliverable trained model.

## Text model format

First line: `LFNST_REPTREE_V1 13 NODE_COUNT`. Subsequent lines are `id feature threshold left_id right_id missing_left_weight p0 p1`. IDs are contiguous preorder beginning at zero. All doubles use Java's full-precision `Double.toString`; no rounded tree parsing. Internal nodes select left exactly when `feature_value < threshold`, otherwise right. Leaves use feature `-1` and children `-1`. Predict class 0 for `p0 >= p1`, including ties. Missing features mix child probabilities with the stored weight; the encoder may instead conservatively decline to prune nonfinite features. Export refuses empty WEKA distributions rather than silently changing their semantics.

The Java exporter compares real WEKA inference against node inference for training and validation plus below/exact/above split and missing-feature probes. Python independently parses the text model and verifies every validation probability (absolute tolerance `1e-12`).
