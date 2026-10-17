param(
  [switch]$Smoke,
  [string]$Root = "I:\vvenc-LFNST\lahtp_runs\sjtu_patch_stretch_12_2",
  [string]$Encoder = "I:\vvenc-LFNST\bin\release-static\vvencapp.exe"
)

$ErrorActionPreference = 'Stop'
$repo = "I:\vvenc-LFNST"
$gen = Join-Path $repo "tools\lard_lfnst_patch_stretch_12_2.py"
$analyze = Join-Path $repo "tools\lard_lfnst_patch_mechanism_12_2.py"
$seqDir = Join-Path $Root "sequences"
$encRoot = Join-Path $Root "encodes"
$manifestDir = Join-Path $Root "manifests"
$analysisDir = Join-Path $Root "analysis"
New-Item -ItemType Directory -Force -Path $Root,$seqDir,$encRoot,$manifestDir,$analysisDir | Out-Null

if ($Smoke) {
  $splits = @("validation")
  $stretch = @("1","2")
  $qps = @(32)
} else {
  $splits = @("train","validation")
  $stretch = @("1","1.15","1.41","2","3.86","5")
  $qps = @(22,27,32,37)
}

python $gen generate --out-dir $Root --splits $splits --stretch $stretch --reuse-manifest
if ($LASTEXITCODE -ne 0) { throw "patch sequence generation failed" }

function StretchName([string]$s) {
  return $s.Replace(".", "p")
}

$summary = @()
foreach ($split in $splits) {
  foreach ($s in $stretch) {
    $sn = StretchName $s
    $input = Join-Path $seqDir "sjtu_$($split)_patch256_s$($sn)_512x512_16f.yuv"
    if (!(Test-Path $input)) { throw "missing generated input $input" }
    foreach ($qp in $qps) {
      $case = Join-Path $encRoot "$($split)_s$($sn)_QP$qp"
      New-Item -ItemType Directory -Force -Path $case | Out-Null
      $trace = Join-Path $case "trace.csv"
      $bitstream = Join-Path $case "anchor.vvc"
      $log = Join-Path $case "anchor.log"
      Remove-Item -LiteralPath $trace,$bitstream,$log -Force -ErrorAction SilentlyContinue

      $traceRel = "lahtp_runs/sjtu_patch_stretch_12_2/encodes/$($split)_s$($sn)_QP$qp/trace.csv"
      $common = @("--preset","medium","-i",$input,"-s","512x512","-r","30","-c","yuv420","-q","$qp","--qpa","0","-f","16","-ip","1","--mtprofile","0","--threads","1")
      $sw = [Diagnostics.Stopwatch]::StartNew()
      & $Encoder @common --additional "LardLfnstTraceFile=$traceRel LardLfnstSkip=0" -o $bitstream 2>&1 | Tee-Object -FilePath $log | Out-Null
      if ($LASTEXITCODE -ne 0) { throw "encode failed split=$split s=$s QP=$qp" }
      $sw.Stop()
      $summary += [pscustomobject]@{
        Split=$split
        Stretch=$s
        QP=$qp
        Seconds=[math]::Round($sw.Elapsed.TotalSeconds,3)
        Bytes=(Get-Item $bitstream).Length
        TraceBytes=(Get-Item $trace).Length
      }
      $summary | Export-Csv -NoTypeInformation (Join-Path $Root "encode_summary.csv")
      Write-Host "done split=$split s=$s QP=$qp seconds=$([math]::Round($sw.Elapsed.TotalSeconds,3))"
    }
  }
}

$maxArg = @()
if ($Smoke) {
  $maxArg = @("--max-blocks-per-trace","20000")
}
python $analyze --run-root $encRoot --manifest-dir $manifestDir --out-dir $analysisDir @maxArg
if ($LASTEXITCODE -ne 0) { throw "analysis failed" }

$summary | Format-Table -AutoSize
