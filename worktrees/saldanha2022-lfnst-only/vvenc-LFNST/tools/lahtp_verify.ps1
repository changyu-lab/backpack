param(
  [string]$Encoder = (Join-Path $PSScriptRoot "..\bin\release-static\vvencapp.exe"),
  [string]$InputYuv = (Join-Path $PSScriptRoot "..\test\data\RTn23_80x44p15_f15.yuv"),
  [string]$Size = "80x44",
  [int]$FrameRate = 15,
  [int]$Frames = 4,
  [int]$SmokeFrames = 2,
  [string]$Preset = "medium",
  [int]$IntraPeriod = 32,
  [int]$Strength = 2,
  [string]$OutputDir = (Join-Path $PSScriptRoot "..\lahtp_runs\verify"),
  [switch]$RunAnalysis
)

$ErrorActionPreference = "Stop"

function Invoke-Checked {
  param(
    [string]$Exe,
    [string[]]$ArgList
  )

  & $Exe @ArgList
  if ($LASTEXITCODE -ne 0) {
    throw "Command failed with exit code ${LASTEXITCODE}: $Exe $($ArgList -join ' ')"
  }
}

function Get-CsvCount {
  param([string]$CsvPath, [string]$Field, [string]$Value)
  if (!(Test-Path $CsvPath)) {
    return 0
  }
  return (Import-Csv $CsvPath | Where-Object { $_.$Field -eq $Value } | Measure-Object).Count
}

$Encoder = (Resolve-Path $Encoder).Path
$InputYuv = (Resolve-Path $InputYuv).Path
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$OutputDir = (Resolve-Path $OutputDir).Path

$baseVvc = Join-Path $OutputDir "mode0_no_trace.vvc"
$traceVvc = Join-Path $OutputDir "mode0_trace.vvc"
$traceCsv = Join-Path $OutputDir "mode0_trace.csv"
Remove-Item -LiteralPath $baseVvc,$traceVvc,$traceCsv -ErrorAction SilentlyContinue

$common = @(
  "--preset", $Preset,
  "-s", $Size,
  "-r", "$FrameRate",
  "-i", $InputYuv,
  "-ip", "$IntraPeriod",
  "-f", "$Frames",
  "--mtprofile", "0",
  "--threads", "1"
)

Invoke-Checked $Encoder ($common + @("-o", $baseVvc))
Invoke-Checked $Encoder ($common + @("--lfnstmtstracefile", $traceCsv, "--lfnstmtsprunemode", "0", "-o", $traceVvc))

$baseHash = (Get-FileHash $baseVvc -Algorithm SHA256).Hash
$traceHash = (Get-FileHash $traceVvc -Algorithm SHA256).Hash
if ($baseHash -ne $traceHash) {
  throw "PruneMode=0 trace changed bitstream: $baseHash != $traceHash"
}

$rows = (Import-Csv $traceCsv | Measure-Object).Count
$summary = @(
  [pscustomobject]@{
    Test = "mode0 bit-identical"
    Mode = 0
    BitstreamBytes = (Get-Item $baseVvc).Length
    CsvBytes = (Get-Item $traceCsv).Length
    Rows = $rows
    MtsPrunedRows = 0
    LfnstPrunedRows = 0
    Sha256 = $baseHash
  }
)

foreach ($mode in 1,2,3) {
  $outVvc = Join-Path $OutputDir "mode${mode}.vvc"
  $outCsv = Join-Path $OutputDir "mode${mode}.csv"
  Remove-Item -LiteralPath $outVvc,$outCsv -ErrorAction SilentlyContinue

  Invoke-Checked $Encoder (
    $common +
    @(
      "-f", "$SmokeFrames",
      "--lfnstmtstracefile", $outCsv,
      "--lfnstmtsprunemode", "$mode",
      "--lfnstmtsprunestrength", "$Strength",
      "-o", $outVvc
    )
  )

  $summary += [pscustomobject]@{
    Test = "smoke"
    Mode = $mode
    BitstreamBytes = (Get-Item $outVvc).Length
    CsvBytes = (Get-Item $outCsv).Length
    Rows = (Import-Csv $outCsv | Measure-Object).Count
    MtsPrunedRows = Get-CsvCount $outCsv "mtsPruned" "1"
    LfnstPrunedRows = Get-CsvCount $outCsv "lfnstPruned" "1"
    Sha256 = (Get-FileHash $outVvc -Algorithm SHA256).Hash
  }
}

$summaryPath = Join-Path $OutputDir "summary.csv"
$summary | Export-Csv -NoTypeInformation $summaryPath
$summary | Format-Table -AutoSize

if ($RunAnalysis) {
  $analysisPath = Join-Path $OutputDir "mode0_analysis.txt"
  python (Join-Path $PSScriptRoot "lahtp_analyze.py") $traceCsv --tau0 0 --skip-quantile 0.9 | Tee-Object -FilePath $analysisPath
}

Write-Host "LAHTP verification completed. Output: $OutputDir"
