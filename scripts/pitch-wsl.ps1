param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PitchArgs
)

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

& python -m pitch route run wsl @PitchArgs
exit $LASTEXITCODE
