param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$CommandArguments
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$pythonExecutable = if (Test-Path -LiteralPath $venvPython) { $venvPython } else { "python" }
$mainFile = Join-Path $projectRoot "main.py"
$utf8 = [System.Text.UTF8Encoding]::new($false)
$previousConsoleOutputEncoding = [Console]::OutputEncoding
$previousOutputEncoding = $OutputEncoding
$previousPythonIoEncoding = $env:PYTHONIOENCODING
$previousMergeOutput = $env:YOUTUBE_AI_MERGE_OUTPUT
$processExitCode = 0

try {
    [Console]::OutputEncoding = $utf8
    $OutputEncoding = $utf8
    $env:PYTHONIOENCODING = "utf-8"
    $env:YOUTUBE_AI_MERGE_OUTPUT = "1"

    & $pythonExecutable $mainFile @CommandArguments | Out-Host
    $processExitCode = $LASTEXITCODE
}
finally {
    [Console]::OutputEncoding = $previousConsoleOutputEncoding
    $OutputEncoding = $previousOutputEncoding
    if ($null -eq $previousPythonIoEncoding) {
        Remove-Item Env:PYTHONIOENCODING -ErrorAction SilentlyContinue
    }
    else {
        $env:PYTHONIOENCODING = $previousPythonIoEncoding
    }
    if ($null -eq $previousMergeOutput) {
        Remove-Item Env:YOUTUBE_AI_MERGE_OUTPUT -ErrorAction SilentlyContinue
    }
    else {
        $env:YOUTUBE_AI_MERGE_OUTPUT = $previousMergeOutput
    }
}

if ($processExitCode -ne 0) {
    exit $processExitCode
}
