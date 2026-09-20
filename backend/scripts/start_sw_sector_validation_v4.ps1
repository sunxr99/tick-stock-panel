param(
  [string]$DataDir = "..\data"
)
$ErrorActionPreference = "Stop"
$backend = Split-Path -Parent $PSScriptRoot
$output = Join-Path $backend "data\research\sw_sector_validation_v4"
$logs = Join-Path (Split-Path -Parent $backend) "logs"
New-Item -ItemType Directory -Force $output, $logs | Out-Null
$python = Join-Path $backend ".venv\Scripts\python.exe"
$script = Join-Path $PSScriptRoot "run_sw_sector_independent_validation_v4.py"
$log = Join-Path $logs "sw_sector_validation_v4.log"
$stdout = Join-Path $logs "sw_sector_validation_v4.stdout.log"
$stderr = Join-Path $logs "sw_sector_validation_v4.stderr.log"
$null = New-Item -ItemType File -Force $log
$process = Start-Process -FilePath $python -ArgumentList @($script, "--data-dir", $DataDir, "--output-dir", $output, "--log-file", $log) -WorkingDirectory $backend -RedirectStandardOutput $stdout -RedirectStandardError $stderr -WindowStyle Hidden -PassThru
$info = @{ pid = $process.Id; start_time = (Get-Date).ToString("o"); python_script = $script; log_file = $log; output_dir = $output; random_seed = 20260919; bootstrap_seed = 20260920; validation_date_count = 48 } | ConvertTo-Json
$info | Set-Content -LiteralPath (Join-Path $output "run_info.json") -Encoding utf8
Write-Output $process.Id
