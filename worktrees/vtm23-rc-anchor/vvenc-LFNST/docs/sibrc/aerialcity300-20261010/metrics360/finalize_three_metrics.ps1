$ErrorActionPreference='Stop'
$taskProcess=Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -like '*sibrc300_metrics_20261010.py*' }
if($taskProcess){Wait-Process -Id $taskProcess.ProcessId}
$taskData='I:/vvenc-LFNST/.worktrees/sibrc300-20261010/metrics360'
if(-not (Test-Path "$taskData/assessment.json")){throw 'Metrics pipeline did not complete'}
& 'F:/Anaconda/python.exe' 'I:/vvenc-LFNST/.worktrees/validate_three_metrics.py'
if($LASTEXITCODE -ne 0){throw 'Result verification failed'}
& 'F:/Anaconda/python.exe' 'I:/vvenc-LFNST/.worktrees/sibrc300_metrics_report.py'
if($LASTEXITCODE -ne 0){throw 'Report generation failed'}
$env:MPLCONFIGDIR='I:/vvenc-LFNST/.worktrees/sibrc300-mplconfig'
& 'F:/Anaconda/python.exe' 'I:/vvenc-LFNST/.worktrees/sibrc300_frameplots_20261010.py'
if($LASTEXITCODE -ne 0){throw 'Preview generation failed'}
& 'F:/Anaconda/python.exe' 'I:/vvenc-LFNST/.worktrees/sibrc300_frameplots_20261010.py' --export
if($LASTEXITCODE -ne 0){throw 'Figure export failed'}
& 'C:/Users/hitxi/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' 'I:/vvenc-LFNST/.codex/skills/scipilot-figure-skill/scripts/check_figure.py' "$taskData/frame_bitrate.png" "$taskData/frame_spsnr.png" --strict
if($LASTEXITCODE -ne 0){throw 'Figure compliance failed'}
$taskArchive='C:/Users/hitxi/.codex/worktrees/vtm23-rc-anchor/vvenc-LFNST/docs/sibrc/aerialcity300-20261010/metrics360'
New-Item -ItemType Directory -Path $taskArchive -Force | Out-Null
Get-ChildItem -LiteralPath $taskData -File | Where-Object { $_.Extension -in '.json','.csv','.md','.txt','.png','.pdf','.svg','.cpp','.log' } | Copy-Item -Destination $taskArchive
foreach($taskName in 'sibrc300_metrics_20261010.py','sibrc300_frameplots_20261010.py','sibrc300_metrics_report.py','validate_three_metrics.py','metrics360_manifest.py','verify_metrics_corrected_actual3.py'){
 Copy-Item -LiteralPath "I:/vvenc-LFNST/.worktrees/$taskName" -Destination $taskArchive
}
Write-Output 'FINALIZATION COMPLETE; visual preview review still required'
