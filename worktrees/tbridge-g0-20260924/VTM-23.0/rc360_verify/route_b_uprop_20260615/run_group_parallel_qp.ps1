param(
  [Parameter(Mandatory = $true)]
  [ValidateSet('B0', 'B1', 'B2', 'B3')]
  [string]$Group
)

$ErrorActionPreference = 'Stop'
Remove-Item Env:\RC360_IBRC_SEQUENCE -ErrorAction SilentlyContinue

$root = 'I:\001-IBRC-exps\VTM-23.0'
$experimentRoot = Join-Path $root 'rc360_verify\route_b_uprop_20260615\fullres_ablation_fixed'
$bin = Join-Path $root 'bin\vs16\msvc-19.29\x86_64\release\EncoderApp.exe'
$seq = 'I:\Sequences360\AerialCity_3840x1920_30fps_8bit_420_erp.yuv'
$sph = Join-Path $root 'cfg-360Lib\360Lib\sphere_655362.txt'
$groups = @{
  B0 = @{ Name = 'B0_frozen6A_parity'; Frame = 0; Ctu = 0; Enabled = 0 }
  B1 = @{ Name = 'B1_ctu_uprop';       Frame = 0; Ctu = 1; Enabled = 1 }
  B2 = @{ Name = 'B2_frame_uprop';     Frame = 1; Ctu = 0; Enabled = 1 }
  B3 = @{ Name = 'B3_frame_ctu_uprop'; Frame = 1; Ctu = 1; Enabled = 1 }
}
$points = @(
  @{ Qp = 22; Target = 18484890; InitialQp = $null },
  @{ Qp = 27; Target = 4622535;  InitialQp = $null },
  @{ Qp = 32; Target = 2189700;  InitialQp = 34 },
  @{ Qp = 37; Target = 1191780;  InitialQp = 42 }
)
$definition = $groups[$Group]
$out = Join-Path $experimentRoot $definition.Name
$status = Join-Path $out 'parallel_status.log'

function Write-Status([string]$message) {
  Add-Content -Path $status -Value ("{0} {1}" -f (Get-Date).ToString('o'), $message)
}

function New-EncoderArguments($point, [string]$pointDir) {
  $args = @(
    '-c', (Join-Path $root 'cfg\encoder_lowdelay_P_vtm.cfg'),
    '-c', (Join-Path $root 'cfg-360Lib\encoder_360_ERP.cfg'),
    '-c', (Join-Path $root 'cfg-360Lib\per-sequence\360\360test_AerialCity.cfg'),
    '-c', (Join-Path $root 'cfg\rc360_ieff_only_ctu_rd_aerialcity3840.cfg'),
    '-i', $seq,
    '-wdt', '3840', '-hgt', '1920', '-fr', '30', '-f', '16',
    '--InputBitDepth=8', '--FramesToBeEncoded=16',
    '--RateControl=1', '--LCULevelRateControl=1', '--RCLCUSeparateModel=1',
    '--WaveFrontSynchro=0',
    '--RC360IBRC=1', '--RC360FbTc=0',
    '--RC360IBRCCtuLevel=1', '--RC360IBRCCtuMode=1',
    '--RC360IBRCModelUpdate=0',
    ("--RC360Uprop={0}" -f $definition.Enabled),
    ("--RC360UpropFrame={0}" -f $definition.Frame),
    ("--RC360UpropCtu={0}" -f $definition.Ctu),
    '--RC360UpropAlpha=0.30', '--RC360UpropBeta=0.20',
    '--RC360UpropMin=0.70', '--RC360UpropMax=1.50',
    '--RC360UpropFrameMin=0.95', '--RC360UpropFrameMax=1.05',
    '--RC360UpropSearchRange=16', '--RC360UpropSearchStep=4',
    '--CodingFaceWidth=3840', '--CodingFaceHeight=1920',
    '--WSPSNR=1', '--E2EWSPSNR=1', '--SPSNR_NN=1',
    '--CPP_PSNR=1', '--CF_CPP_PSNR=1',
    '--ViewPortPSNREnable=0', '--DynamicViewPortPSNREnable=0',
    ("--SphFile={0}" -f $sph),
    '-q', $point.Qp.ToString(),
    ("--TargetBitrate={0}" -f $point.Target),
    '-b', (Join-Path $pointDir 'str.bin'),
    '-o', (Join-Path $pointDir 'rec.yuv')
  )
  if ($null -ne $point.InitialQp) {
    $args += ("--InitialQP={0}" -f $point.InitialQp)
  }
  return $args
}

New-Item -ItemType Directory -Force -Path $out | Out-Null
Get-FileHash $bin -Algorithm SHA256 | ConvertTo-Json | Set-Content (Join-Path $out 'binary_sha256.json')
git -C $root rev-parse HEAD | Set-Content (Join-Path $out 'git_head.txt')
Write-Status ("GROUP START {0}; four QPs parallel" -f $Group)
$jobs = @()

foreach ($point in $points) {
  $qp = [int]$point.Qp
  $pointDir = Join-Path $out ("QP{0}" -f $qp)
  New-Item -ItemType Directory -Force -Path $pointDir | Out-Null
  Remove-Item (Join-Path $pointDir 'encode.log'), (Join-Path $pointDir 'encode.stderr.log'),
              (Join-Path $pointDir 'str.bin'), (Join-Path $pointDir 'rec.yuv') `
              -Force -ErrorAction SilentlyContinue
  $args = New-EncoderArguments $point $pointDir
  [ordered]@{
    start = (Get-Date).ToString('o')
    group = $Group
    qp = $qp
    target = $point.Target
    initialQP = $point.InitialQp
    binary = $bin
    sequence = $seq
    arguments = $args
  } | ConvertTo-Json -Depth 4 | Set-Content (Join-Path $pointDir 'run_snapshot.json')

  $process = Start-Process -FilePath $bin -ArgumentList $args -WorkingDirectory $root `
    -RedirectStandardOutput (Join-Path $pointDir 'encode.log') `
    -RedirectStandardError (Join-Path $pointDir 'encode.stderr.log') `
    -WindowStyle Hidden -PassThru
  $process.Id | Set-Content (Join-Path $pointDir 'pid.txt')
  $jobs += [pscustomobject]@{ Qp = $qp; Process = $process }
  Write-Status ("START QP{0} pid={1}" -f $qp, $process.Id)
}

foreach ($job in $jobs) {
  $job.Process.WaitForExit()
  $pointDir = Join-Path $out ("QP{0}" -f $job.Qp)
  $log = Join-Path $pointDir 'encode.log'
  if ($job.Process.ExitCode -ne 0) {
    throw "QP$($job.Qp) failed with exit code $($job.Process.ExitCode)"
  }
  if (-not (Select-String -Path $log -Pattern 'finished @' -Quiet)) {
    throw "QP$($job.Qp) has no finished marker"
  }
  if (-not (Select-String -Path $log -Pattern '^\s*16\s+a\s+' -Quiet)) {
    throw "QP$($job.Qp) has no 16-frame summary"
  }
  $stderr = Join-Path $pointDir 'encode.stderr.log'
  if ((Get-Item $stderr).Length -ne 0) {
    throw "QP$($job.Qp) produced stderr output"
  }
  Remove-Item (Join-Path $pointDir 'rec.yuv') -Force -ErrorAction SilentlyContinue
  Write-Status ("DONE QP{0}" -f $job.Qp)
}

Write-Status ("GROUP DONE {0}" -f $Group)
