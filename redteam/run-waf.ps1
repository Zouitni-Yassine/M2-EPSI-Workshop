param([ValidateSet('preflight','waf','soc')][string]$Scenario = 'waf', [switch]$Execute)
$runnerArgs = @((Join-Path $PSScriptRoot 'run.py'), '--scenario', $Scenario)
if ($Execute) { $runnerArgs += '--execute' }
python @runnerArgs
exit $LASTEXITCODE
