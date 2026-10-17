#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
import stat
import time

import paramiko


HOST = "ry2.9gpu.com"
PORT = 16021
USER = "root"
REMOTE_ROOT = "/root/vvenc_lard_exp"
REMOTE_SRC = f"{REMOTE_ROOT}/vvenc-1.12.0-lard-src"
REMOTE_TOOLS = f"{REMOTE_ROOT}/tools"


FILES = [
    ("include/vvenc/vvencCfg.h", f"{REMOTE_SRC}/include/vvenc/vvencCfg.h"),
    ("source/Lib/CommonLib/TypeDef.h", f"{REMOTE_SRC}/source/Lib/CommonLib/TypeDef.h"),
    ("source/Lib/CommonLib/TrQuant.h", f"{REMOTE_SRC}/source/Lib/CommonLib/TrQuant.h"),
    ("source/Lib/CommonLib/TrQuant.cpp", f"{REMOTE_SRC}/source/Lib/CommonLib/TrQuant.cpp"),
    ("source/Lib/EncoderLib/EncCu.cpp", f"{REMOTE_SRC}/source/Lib/EncoderLib/EncCu.cpp"),
    ("source/Lib/EncoderLib/IntraSearch.cpp", f"{REMOTE_SRC}/source/Lib/EncoderLib/IntraSearch.cpp"),
    ("source/Lib/EncoderLib/IntraSearch.h", f"{REMOTE_SRC}/source/Lib/EncoderLib/IntraSearch.h"),
    ("source/Lib/EncoderLib/LardLfnstCovTable.h", f"{REMOTE_SRC}/source/Lib/EncoderLib/LardLfnstCovTable.h"),
    ("source/Lib/EncoderLib/LardLfnstCovTable.cpp", f"{REMOTE_SRC}/source/Lib/EncoderLib/LardLfnstCovTable.cpp"),
    ("source/Lib/EncoderLib/LardLfnstSkip16FitTable.inc", f"{REMOTE_SRC}/source/Lib/EncoderLib/LardLfnstSkip16FitTable.inc"),
    ("source/Lib/EncoderLib/LardLfnstSkip17FitTable.inc", f"{REMOTE_SRC}/source/Lib/EncoderLib/LardLfnstSkip17FitTable.inc"),
    ("source/Lib/EncoderLib/LardLfnstSkip18FitTable.inc", f"{REMOTE_SRC}/source/Lib/EncoderLib/LardLfnstSkip18FitTable.inc"),
    ("source/Lib/EncoderLib/LardLfnstSkip18CheapGate.inc", f"{REMOTE_SRC}/source/Lib/EncoderLib/LardLfnstSkip18CheapGate.inc"),
    ("source/Lib/EncoderLib/LardLfnstSkip20DirectMaskTable.inc", f"{REMOTE_SRC}/source/Lib/EncoderLib/LardLfnstSkip20DirectMaskTable.inc"),
    ("source/Lib/EncoderLib/LardLfnstSkip21TheoryTable.inc", f"{REMOTE_SRC}/source/Lib/EncoderLib/LardLfnstSkip21TheoryTable.inc"),
    ("source/Lib/EncoderLib/LardLfnstCandGainTable.inc", f"{REMOTE_SRC}/source/Lib/EncoderLib/LardLfnstCandGainTable.inc"),
    ("source/Lib/EncoderLib/LardLfnst2ndCorrTable.inc", f"{REMOTE_SRC}/source/Lib/EncoderLib/LardLfnst2ndCorrTable.inc"),
    ("source/Lib/EncoderLib/LardLfnst2ndScoreTable.inc", f"{REMOTE_SRC}/source/Lib/EncoderLib/LardLfnst2ndScoreTable.inc"),
    ("source/Lib/EncoderLib/LardLfnst2ndCoffTable.inc", f"{REMOTE_SRC}/source/Lib/EncoderLib/LardLfnst2ndCoffTable.inc"),
    ("source/Lib/EncoderLib/LardLfnstTheoryStatsTable.inc", f"{REMOTE_SRC}/source/Lib/EncoderLib/LardLfnstTheoryStatsTable.inc"),
    ("source/Lib/EncoderLib/LardLfnstFitTable.inc", f"{REMOTE_SRC}/source/Lib/EncoderLib/LardLfnstFitTable.inc"),
    ("source/Lib/EncoderLib/LardLfnstModeSkipTable.inc", f"{REMOTE_SRC}/source/Lib/EncoderLib/LardLfnstModeSkipTable.inc"),
    ("source/Lib/EncoderLib/LardLfnstSpeedTable.inc", f"{REMOTE_SRC}/source/Lib/EncoderLib/LardLfnstSpeedTable.inc"),
    ("source/Lib/apputils/VVEncAppCfg.h", f"{REMOTE_SRC}/source/Lib/apputils/VVEncAppCfg.h"),
    ("source/Lib/vvenc/CMakeLists.txt", f"{REMOTE_SRC}/source/Lib/vvenc/CMakeLists.txt"),
    ("source/Lib/vvenc/vvencCfg.cpp", f"{REMOTE_SRC}/source/Lib/vvenc/vvencCfg.cpp"),
    ("tools/lard_360_metrics.py", f"{REMOTE_TOOLS}/lard_360_metrics.py"),
    ("tools/lard_lfnst_scan_2nd_params.py", f"{REMOTE_TOOLS}/lard_lfnst_scan_2nd_params.py"),
    ("tools/compute_lfnst_theory_stats.py", f"{REMOTE_TOOLS}/compute_lfnst_theory_stats.py"),
    ("tools/lard_lfnst/generate_lard_lfnst_cov_table.py", f"{REMOTE_TOOLS}/lard_lfnst/generate_lard_lfnst_cov_table.py"),
    ("tools/lard_lfnst/verify_lard_lfnst_table.py", f"{REMOTE_TOOLS}/lard_lfnst/verify_lard_lfnst_table.py"),
    ("tools/lard_lfnst/verify_lard_lfnst_trace.py", f"{REMOTE_TOOLS}/lard_lfnst/verify_lard_lfnst_trace.py"),
    ("tools/lard_lfnst/analyze_lard_lfnst_cov_logs.py", f"{REMOTE_TOOLS}/lard_lfnst/analyze_lard_lfnst_cov_logs.py"),
    ("tools/lard_lfnst/diagnose_lard_lfnst_cov.py", f"{REMOTE_TOOLS}/lard_lfnst/diagnose_lard_lfnst_cov.py"),
    ("tools/lard_lfnst/fit_lard_lfnst_skip16.py", f"{REMOTE_TOOLS}/lard_lfnst/fit_lard_lfnst_skip16.py"),
    ("tools/lard_lfnst/fit_lard_lfnst_skip18_cheap_gate.py", f"{REMOTE_TOOLS}/lard_lfnst/fit_lard_lfnst_skip18_cheap_gate.py"),
    ("tools/lard_lfnst/run_skip18_paired_repeats.py", f"{REMOTE_TOOLS}/lard_lfnst/run_skip18_paired_repeats.py"),
    ("tools/lard_lfnst/skip19_policy.py", f"{REMOTE_TOOLS}/lard_lfnst/skip19_policy.py"),
    ("tools/lard_lfnst/run_skip19_t10_sweep.py", f"{REMOTE_TOOLS}/lard_lfnst/run_skip19_t10_sweep.py"),
    ("tools/lard_lfnst/optimize_lard_lfnst_skip20_oracle.py", f"{REMOTE_TOOLS}/lard_lfnst/optimize_lard_lfnst_skip20_oracle.py"),
    ("tools/lard_lfnst/fit_lard_lfnst_skip20_direct.py", f"{REMOTE_TOOLS}/lard_lfnst/fit_lard_lfnst_skip20_direct.py"),
    ("tools/lard_lfnst/summarize_skip21_stage1_stats.py", f"{REMOTE_TOOLS}/lard_lfnst/summarize_skip21_stage1_stats.py"),
    ("tools/lard_lfnst/run_skip21_stage1_validation.py", f"{REMOTE_TOOLS}/lard_lfnst/run_skip21_stage1_validation.py"),
    ("tools/lard_parallel_ts_compare.py", f"{REMOTE_TOOLS}/lard_parallel_ts_compare.py"),
    ("tools/lard_run_erp14_latest.py", f"{REMOTE_TOOLS}/lard_run_erp14_latest.py"),
    ("tools/lard_lfnst2nd_fit_corr_table.py", f"{REMOTE_TOOLS}/lard_lfnst2nd_fit_corr_table.py"),
    ("tools/lard_lfnst2nd_stats_summary.py", f"{REMOTE_TOOLS}/lard_lfnst2nd_stats_summary.py"),
    ("tools/lard_run_eval_360_cleanup.py", f"{REMOTE_TOOLS}/lard_run_eval_360_cleanup.py"),
    ("tools/lard_summarize_caller_count.py", f"{REMOTE_TOOLS}/lard_summarize_caller_count.py"),
    ("tools/lard_summarize_shadow_teacher.py", f"{REMOTE_TOOLS}/lard_summarize_shadow_teacher.py"),
    ("tools/lard_summarize_skip14_step_final.py", f"{REMOTE_TOOLS}/lard_summarize_skip14_step_final.py"),
    ("tools/server_run_lfnst2nd_scan.sh", f"{REMOTE_ROOT}/server_run_lfnst2nd_scan.sh"),
    ("tools/server_run_skip14_shadow_gate3.sh", f"{REMOTE_ROOT}/server_run_skip14_shadow_gate3.sh"),
    ("tools/server_run_skip14_steps_nogate.sh", f"{REMOTE_ROOT}/server_run_skip14_steps_nogate.sh"),
    ("tools/server_run_skip14_timeweighted.sh", f"{REMOTE_ROOT}/server_run_skip14_timeweighted.sh"),
    ("tools/server_run_skip14_small_exps.sh", f"{REMOTE_ROOT}/server_run_skip14_small_exps.sh"),
    ("tools/server_run_skip15_cov_phase4.sh", f"{REMOTE_ROOT}/server_run_skip15_cov_phase4.sh"),
    ("tools/server_run_skip15_rd_diag.sh", f"{REMOTE_ROOT}/server_run_skip15_rd_diag.sh"),
    ("tools/server_run_skip16_rd_diag.sh", f"{REMOTE_ROOT}/server_run_skip16_rd_diag.sh"),
    ("tools/server_run_skip17_rd_diag.sh", f"{REMOTE_ROOT}/server_run_skip17_rd_diag.sh"),
    ("tools/server_run_skip18_rd_diag.sh", f"{REMOTE_ROOT}/server_run_skip18_rd_diag.sh"),
    ("tools/server_run_skip18_real5_eval.sh", f"{REMOTE_ROOT}/server_run_skip18_real5_eval.sh"),
    ("tools/server_run_skip18_v4_repeats.sh", f"{REMOTE_ROOT}/server_run_skip18_v4_repeats.sh"),
    ("tools/server_run_skip19_t10_sweep.sh", f"{REMOTE_ROOT}/server_run_skip19_t10_sweep.sh"),
    ("tools/server_run_skip20_oracle_trace.sh", f"{REMOTE_ROOT}/server_run_skip20_oracle_trace.sh"),
    ("tools/server_run_skip20_profiles.sh", f"{REMOTE_ROOT}/server_run_skip20_profiles.sh"),
    ("tools/server_run_skip20_v2.sh", f"{REMOTE_ROOT}/server_run_skip20_v2.sh"),
    ("tools/server_run_skip20_v2_real.sh", f"{REMOTE_ROOT}/server_run_skip20_v2_real.sh"),
    ("tools/server_run_skip21_stage1_validation.sh", f"{REMOTE_ROOT}/server_run_skip21_stage1_validation.sh"),
]


def main() -> None:
    password = os.environ.get("ERP_SERVER_PASSWORD")
    key_path = Path(os.environ.get("ERP_SERVER_KEY", str(Path.home() / ".ssh" / "codex_ry2_ipm")))
    root = Path.cwd()

    client = None
    for attempt in range(1, 11):
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            kwargs = dict(hostname=HOST, port=PORT, username=USER, timeout=60, banner_timeout=180, auth_timeout=180)
            if password:
                kwargs["password"] = password
            elif key_path.exists():
                kwargs["key_filename"] = str(key_path)
            else:
                raise RuntimeError("set ERP_SERVER_PASSWORD or ERP_SERVER_KEY")
            client.connect(**kwargs)
            break
        except Exception:
            try:
                client.close()
            except Exception:
                pass
            if attempt == 10:
                raise
            time.sleep(30)
    sftp = client.open_sftp()

    for local_rel, remote in FILES:
        local = root / local_rel
        if not local.exists():
            raise FileNotFoundError(local)
        parent = str(Path(remote).parent).replace("\\", "/")
        client.exec_command(f"mkdir -p {parent}")[1].channel.recv_exit_status()
        sftp.put(str(local), remote)
        if remote.endswith(".sh") or remote.endswith(".py"):
            mode = sftp.stat(remote).st_mode
            sftp.chmod(remote, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        print(f"{local_rel} -> {remote}")

    sftp.close()
    _, stdout, stderr = client.exec_command(f"bash -n {REMOTE_ROOT}/server_run_lfnst2nd_scan.sh && bash -n {REMOTE_ROOT}/server_run_skip14_shadow_gate3.sh && bash -n {REMOTE_ROOT}/server_run_skip14_steps_nogate.sh && bash -n {REMOTE_ROOT}/server_run_skip14_timeweighted.sh && bash -n {REMOTE_ROOT}/server_run_skip14_small_exps.sh && bash -n {REMOTE_ROOT}/server_run_skip15_cov_phase4.sh && bash -n {REMOTE_ROOT}/server_run_skip15_rd_diag.sh && bash -n {REMOTE_ROOT}/server_run_skip16_rd_diag.sh && bash -n {REMOTE_ROOT}/server_run_skip17_rd_diag.sh && bash -n {REMOTE_ROOT}/server_run_skip18_rd_diag.sh && bash -n {REMOTE_ROOT}/server_run_skip18_real5_eval.sh && bash -n {REMOTE_ROOT}/server_run_skip18_v4_repeats.sh && bash -n {REMOTE_ROOT}/server_run_skip19_t10_sweep.sh && bash -n {REMOTE_ROOT}/server_run_skip20_oracle_trace.sh && bash -n {REMOTE_ROOT}/server_run_skip20_profiles.sh && bash -n {REMOTE_ROOT}/server_run_skip20_v2.sh && bash -n {REMOTE_ROOT}/server_run_skip20_v2_real.sh && bash -n {REMOTE_ROOT}/server_run_skip21_stage1_validation.sh && python3 -m py_compile {REMOTE_TOOLS}/lard_lfnst_scan_2nd_params.py {REMOTE_TOOLS}/compute_lfnst_theory_stats.py {REMOTE_TOOLS}/lard_lfnst/generate_lard_lfnst_cov_table.py {REMOTE_TOOLS}/lard_lfnst/verify_lard_lfnst_table.py {REMOTE_TOOLS}/lard_lfnst/verify_lard_lfnst_trace.py {REMOTE_TOOLS}/lard_lfnst/analyze_lard_lfnst_cov_logs.py {REMOTE_TOOLS}/lard_lfnst/diagnose_lard_lfnst_cov.py {REMOTE_TOOLS}/lard_lfnst/fit_lard_lfnst_skip16.py {REMOTE_TOOLS}/lard_lfnst/fit_lard_lfnst_skip18_cheap_gate.py {REMOTE_TOOLS}/lard_lfnst/run_skip18_paired_repeats.py {REMOTE_TOOLS}/lard_lfnst/skip19_policy.py {REMOTE_TOOLS}/lard_lfnst/run_skip19_t10_sweep.py {REMOTE_TOOLS}/lard_lfnst/optimize_lard_lfnst_skip20_oracle.py {REMOTE_TOOLS}/lard_lfnst/fit_lard_lfnst_skip20_direct.py {REMOTE_TOOLS}/lard_lfnst/summarize_skip21_stage1_stats.py {REMOTE_TOOLS}/lard_lfnst/run_skip21_stage1_validation.py {REMOTE_TOOLS}/lard_parallel_ts_compare.py {REMOTE_TOOLS}/lard_run_erp14_latest.py {REMOTE_TOOLS}/lard_lfnst2nd_fit_corr_table.py {REMOTE_TOOLS}/lard_lfnst2nd_stats_summary.py {REMOTE_TOOLS}/lard_run_eval_360_cleanup.py {REMOTE_TOOLS}/lard_summarize_caller_count.py {REMOTE_TOOLS}/lard_summarize_shadow_teacher.py {REMOTE_TOOLS}/lard_summarize_skip14_step_final.py {REMOTE_TOOLS}/lard_360_metrics.py", timeout=120)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    if out:
        print(out, end="" if out.endswith("\n") else "\n")
    if err:
        print(err, end="" if err.endswith("\n") else "\n")
    client.close()
    raise SystemExit(code)


if __name__ == "__main__":
    main()
