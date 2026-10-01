[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string[]]$Path
)

$ErrorActionPreference = "Stop"

if (-not $env:WINDOWS_CERTIFICATE_BASE64 -or -not $env:WINDOWS_CERTIFICATE_PASSWORD) {
    throw "WINDOWS_CERTIFICATE_BASE64 and WINDOWS_CERTIFICATE_PASSWORD must be configured."
}

$SignTool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\signtool.exe" |
    Sort-Object FullName -Descending |
    Select-Object -First 1
if (-not $SignTool) {
    throw "Windows SDK signtool.exe was not found."
}

$CertificatePath = Join-Path $env:RUNNER_TEMP "yt-livestream-chatbot-signing.pfx"
[System.IO.File]::WriteAllBytes(
    $CertificatePath,
    [System.Convert]::FromBase64String($env:WINDOWS_CERTIFICATE_BASE64)
)

foreach ($TargetPath in $Path) {
    if (-not (Test-Path -LiteralPath $TargetPath)) {
        throw "Signing target was not found: $TargetPath"
    }
    & $SignTool.FullName sign /fd SHA256 /f $CertificatePath /p $env:WINDOWS_CERTIFICATE_PASSWORD /tr http://timestamp.digicert.com /td SHA256 $TargetPath
    if ($LASTEXITCODE -ne 0) {
        throw "Signing failed: $TargetPath"
    }
}
