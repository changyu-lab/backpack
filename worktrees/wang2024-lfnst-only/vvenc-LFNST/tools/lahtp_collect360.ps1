param(
  [string]$SequenceRoot = "I:\Sequences360",
  [string]$Encoder = (Join-Path $PSScriptRoot "..\bin\release-static\vvencapp.exe"),
  [string]$OutputDir = (Join-Path $PSScriptRoot "..\lahtp_runs\phase1_360"),
  [string[]]$Names = @("DrivingInCity"),
  [string]$Subset = "low",
  [string[]]$Presets = @("fast"),
  [int[]]$Qps = @(32),
  [int]$Frames = 2,
  [int]$IntraPeriod = 32,
  [int]$Mode = 0,
  [int]$Strength = 0,
  [int]$MaxFiles = 0,
  [switch]$NoRecurse,
  [switch]$PreferSmallest,
  [switch]$RunAnalysis,
  [switch]$KeepBitstreams
)

$ErrorActionPreference = "Stop"

function Get-SequenceMeta {
  param([System.IO.FileInfo]$File)

  $name = $File.Name
  if ($name -match '_(?<w>\d+)x(?<h>\d+)_(?<fps>\d+)(fps|Hz)_(?<bd>\d+)(bit|b)_420') {
    $bitDepth = [int]$Matches.bd
    $format = if ($bitDepth -gt 8) { "yuv420_10" } else { "yuv420" }
    return [pscustomobject]@{
      Path = $File.FullName
      Name = [System.IO.Path]::GetFileNameWithoutExtension($File.Name)
      Width = [int]$Matches.w
      Height = [int]$Matches.h
      Size = "$($Matches.w)x$($Matches.h)"
      Fps = [int]$Matches.fps
      BitDepth = $bitDepth
      Format = $format
      Bytes = $File.Length
    }
  }

  return $null
}

function Invoke-Checked {
  param([string]$Exe, [string[]]$ArgList)
  & $Exe @ArgList
  if ($LASTEXITCODE -ne 0) {
    throw "Command failed with exit code ${LASTEXITCODE}: $Exe $($ArgList -join ' ')"
  }
}

function Get-LahtpCsvStats {
  param([string]$CsvPath)

  $rows = 0
  $mtsPruned = 0
  $lfnstPruned = 0
  if (!(Test-Path $CsvPath)) {
    return [pscustomobject]@{ Rows = 0; MtsPrunedRows = 0; LfnstPrunedRows = 0 }
  }

  $reader = [System.IO.StreamReader]::new($CsvPath)
  try {
    $header = $reader.ReadLine()
    if ($null -eq $header) {
      return [pscustomobject]@{ Rows = 0; MtsPrunedRows = 0; LfnstPrunedRows = 0 }
    }

    $cols = $header.Split(',')
    $mtsIdx = [Array]::IndexOf($cols, "mtsPruned")
    $lfnstIdx = [Array]::IndexOf($cols, "lfnstPruned")

    while (($line = $reader.ReadLine()) -ne $null) {
      $rows++
      $parts = $line.Split(',')
      if ($mtsIdx -ge 0 -and $parts.Count -gt $mtsIdx -and $parts[$mtsIdx] -eq "1") {
        $mtsPruned++
      }
      if ($lfnstIdx -ge 0 -and $parts.Count -gt $lfnstIdx -and $parts[$lfnstIdx] -eq "1") {
        $lfnstPruned++
      }
    }
  }
  finally {
    $reader.Close()
  }

  return [pscustomobject]@{ Rows = $rows; MtsPrunedRows = $mtsPruned; LfnstPrunedRows = $lfnstPruned }
}

$Encoder = (Resolve-Path $Encoder).Path
$SequenceRoot = (Resolve-Path $SequenceRoot).Path
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$OutputDir = (Resolve-Path $OutputDir).Path

$searchRoot = if ($Subset -and $Subset -ne ".") { Join-Path $SequenceRoot $Subset } else { $SequenceRoot }
if (!(Test-Path $searchRoot)) {
  throw "Sequence subset path not found: $searchRoot"
}

$childArgs = @{
  LiteralPath = $searchRoot
  File = $true
  Filter = "*.yuv"
}
if (!$NoRecurse) {
  $childArgs.Recurse = $true
}

$files = Get-ChildItem @childArgs |
  ForEach-Object { Get-SequenceMeta $_ } |
  Where-Object { $_ -ne $null }

if ($Names.Count -gt 0 -and $Names[0] -ne "*") {
  $files = $files | Where-Object {
    $seq = $_
    ($Names | Where-Object { $seq.Name -like "*$_*" }).Count -gt 0
  }
}

$files = if ($PreferSmallest) {
  @($files | Sort-Object Bytes, Name)
} else {
  @($files | Sort-Object Name, Width, Height)
}
if ($MaxFiles -gt 0) {
  $files = @($files | Select-Object -First $MaxFiles)
}
if ($files.Count -eq 0) {
  throw "No matching ERP YUV files found under $searchRoot"
}

$summary = @()
foreach ($seq in $files) {
  foreach ($preset in $Presets) {
    foreach ($qp in $Qps) {
      $tag = "{0}_p{1}_q{2}_m{3}_s{4}_f{5}" -f $seq.Name, $preset, $qp, $Mode, $Strength, $Frames
      $safeTag = $tag -replace '[^\w\.-]', '_'
      $outVvc = Join-Path $OutputDir "$safeTag.vvc"
      $outCsv = Join-Path $OutputDir "$safeTag.csv"
      $analysis = Join-Path $OutputDir "$safeTag.analysis.txt"
      Remove-Item -LiteralPath $outVvc,$outCsv,$analysis -ErrorAction SilentlyContinue

      $args = @(
        "--preset", $preset,
        "-s", $seq.Size,
        "-c", $seq.Format,
        "-r", "$($seq.Fps)",
        "-i", $seq.Path,
        "-q", "$qp",
        "-ip", "$IntraPeriod",
        "-f", "$Frames",
        "--mtprofile", "0",
        "--threads", "1",
        "--lfnstmtstracefile", $outCsv,
        "--lfnstmtsprunemode", "$Mode",
        "--lfnstmtsprunestrength", "$Strength",
        "-o", $outVvc
      )

      $start = Get-Date
      Invoke-Checked $Encoder $args
      $elapsed = ((Get-Date) - $start).TotalSeconds

      $csvStats = Get-LahtpCsvStats $outCsv

      if ($RunAnalysis -and (Test-Path $outCsv)) {
        python (Join-Path $PSScriptRoot "lahtp_analyze.py") $outCsv --tau0 0 --skip-quantile 0.9 | Tee-Object -FilePath $analysis
      }

      $summary += [pscustomobject]@{
        Sequence = $seq.Name
        Size = $seq.Size
        Fps = $seq.Fps
        BitDepth = $seq.BitDepth
        Preset = $preset
        QP = $qp
        Mode = $Mode
        Strength = $Strength
        Frames = $Frames
        Seconds = [math]::Round($elapsed, 3)
        BitstreamBytes = (Get-Item $outVvc).Length
        CsvBytes = (Get-Item $outCsv).Length
        Rows = $csvStats.Rows
        MtsPrunedRows = $csvStats.MtsPrunedRows
        LfnstPrunedRows = $csvStats.LfnstPrunedRows
        Csv = $outCsv
        Analysis = if (Test-Path $analysis) { $analysis } else { "" }
      }

      if (!$KeepBitstreams) {
        Remove-Item -LiteralPath $outVvc -ErrorAction SilentlyContinue
      }
    }
  }
}

$summaryPath = Join-Path $OutputDir "summary.csv"
$summary | Export-Csv -NoTypeInformation $summaryPath
$summary | Format-Table -AutoSize
Write-Host "LAHTP 360 collection completed. Summary: $summaryPath"
