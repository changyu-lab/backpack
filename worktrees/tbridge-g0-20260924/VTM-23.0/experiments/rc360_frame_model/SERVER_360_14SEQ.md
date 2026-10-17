# Server 360 14-sequence frame data collection

This runner is intended for a Linux server with the YUV files under:

```bash
/data/360sequence_20f
```

It scans up to 14 `.yuv` files, parses resolution from names containing `WxH`, and encodes sequence groups in parallel.

## Build EncoderApp first

From the VTM root on the server:

```bash
cmake --build build --config Release --target EncoderApp -j
```

If the binary is not auto-detected, pass it explicitly with `--encoder`.

## Run parallel collection

All QPs from 17 to 50:

```bash
python3 experiments/rc360_frame_model/run_server_360_parallel.py \
  --input-dir /data/360sequence_20f \
  --frames 3 \
  --qp-start 17 \
  --qp-end 50 \
  --jobs 4 \
  --tag server_360_14seq_3f_qp17_50 \
  --resume
```

If you want to keep the previous skip list:

```bash
python3 experiments/rc360_frame_model/run_server_360_parallel.py \
  --input-dir /data/360sequence_20f \
  --frames 3 \
  --qp-start 17 \
  --qp-end 50 \
  --skip-qps 22,27,32,37 \
  --jobs 4 \
  --tag server_360_14seq_3f_qp17_50_skip \
  --resume
```

Use `--jobs 14` only if the server has enough CPU and memory for 14 concurrent encoders.

## Outputs

For tag `server_360_14seq_3f_qp17_50`:

```text
experiments/rc360_frame_model/data/server_360_14seq_3f_qp17_50/
+-- sequence_manifest.csv
+-- job_status.csv
+-- failed_jobs.csv              # only if failures occur
+-- all_ctu_samples.csv
+-- frame_samples.csv
+-- ctu/*.csv
```

Logs:

```text
experiments/rc360_frame_model/logs/server_360_14seq_3f_qp17_50/
```

Runs:

```text
experiments/rc360_frame_model/runs/server_360_14seq_3f_qp17_50/
```

## Per-sequence fitting after collection

Rate model:

```bash
python3 experiments/rc360_frame_model/fit_by_sequence_qs_ieff.py \
  --input experiments/rc360_frame_model/data/server_360_14seq_3f_qp17_50/frame_samples.csv \
  --output-dir experiments/rc360_frame_model/results_server_360_14seq_3f_qp17_50/by_sequence_qs_ieff
```

Distortion model:

```bash
python3 experiments/rc360_frame_model/fit_by_sequence_distortion_qs_ieff.py \
  --input experiments/rc360_frame_model/data/server_360_14seq_3f_qp17_50/frame_samples.csv \
  --output-dir experiments/rc360_frame_model/results_server_360_14seq_3f_qp17_50/by_sequence_distortion_qs_ieff
```

The fitting scripts keep P frames only by default using `poc % 8 != 0`.
