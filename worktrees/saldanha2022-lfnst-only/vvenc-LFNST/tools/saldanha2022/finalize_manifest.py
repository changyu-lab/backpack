"""Attach collection provenance and held-out metrics after verified training."""
import csv, json, pathlib, sys
from train import sha, EXCLUDED_NAMES
out=pathlib.Path(sys.argv[1]); collection=pathlib.Path(sys.argv[2])
m=json.loads((out/'manifest.json').read_text())
rows=list(csv.DictReader((out/'validation_predictions.csv').open()))
matrix=[[0,0],[0,0]]
for r in rows: matrix[int(r['label'])][int(r['prediction'])]+=1
m.update(validation_confusion_matrix_actual_by_predicted=matrix,validation_accuracy=sum(matrix[i][i] for i in range(2))/len(rows),explicit_excluded_sequence_names=EXCLUDED_NAMES,collection_plan=json.loads((collection/'collection-plan.json').read_text()),collection_plan_sha256=sha(collection/'collection-plan.json'),collection_results_sha256=sha(collection/'collection-results.json'),adaptation='Saldanha2022-LFNST-only-retrained-VVenC; first frame only; Kimono/ParkScene plus disclosed available HEVC substitutions; strata use recorded CU QP, not command-line QP; no ERP14 training or tuning',equivalence=json.loads((out/'equivalence.json').read_text()),boundary_probes_sha256=sha(out/'probes.csv'))
(out/'manifest.json').write_text(json.dumps(m,indent=2)+'\n')
(out/'README.md').write_text('# Saldanha2022-LFNST-only-retrained-VVenC\n\nGenuine WEKA REPTree3.8.6, seed2022, maximum depth8; node count learned. First-frame only adaptation. Kimono/ParkScene are retained and BasketballPass/BQMall/BasketballDrill/RaceHorses are disclosed training substitutions. FourPeople/BQSquare are disjoint held-out validation substitutions. See manifest for exact collection plan, source file hashes, sampling and metrics. Recorded CU QP (which may differ from encoder command-line QP) defines sampling strata. ERP14 is excluded from all training and tuning. This is a retrained VVenC adaptation, not the original author model.\n')
print(json.dumps({k:m[k] for k in ['node_count','training_rows_available','training_rows_sampled','validation_rows','validation_accuracy','validation_confusion_matrix_actual_by_predicted','max_prediction_error','equivalence','model_sha256']},indent=2))
