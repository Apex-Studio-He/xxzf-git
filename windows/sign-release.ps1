param(
    [Parameter(Mandatory = $true)]
    [string]$Path
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
    throw "Signing target is not a regular file: $Path"
}

$expected = ($env:XXZF_WINDOWS_SIGN_CERT_SHA256 -replace "[^A-Fa-f0-9]", "").ToUpperInvariant()
if ($expected.Length -ne 64) {
    throw "Set XXZF_WINDOWS_SIGN_CERT_SHA256 to the pinned certificate SHA-256 digest"
}

function Get-CertificateSha256([System.Security.Cryptography.X509Certificates.X509Certificate2]$Certificate) {
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($sha256.ComputeHash($Certificate.RawData))).Replace("-", "")
    }
    finally {
        $sha256.Dispose()
    }
}

$matchingCertificates = @()
foreach ($store in @("Cert:\CurrentUser\My", "Cert:\LocalMachine\My")) {
    if (-not (Test-Path $store)) { continue }
    foreach ($certificate in Get-ChildItem $store) {
        if ((Get-CertificateSha256 $certificate) -eq $expected) {
            $matchingCertificates += $certificate
        }
    }
}
if ($matchingCertificates.Count -ne 1) {
    throw "Exactly one private signing certificate must match the pinned SHA-256 digest"
}
$selectorThumbprint = $matchingCertificates[0].Thumbprint

$signtool = $env:XXZF_SIGNTOOL
if ([string]::IsNullOrWhiteSpace($signtool)) {
    $command = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($null -eq $command) {
        throw "signtool.exe was not found; set XXZF_SIGNTOOL"
    }
    $signtool = $command.Source
}

& $signtool sign /fd SHA256 /sha1 $selectorThumbprint /tr https://timestamp.digicert.com /td SHA256 $Path
if ($LASTEXITCODE -ne 0) {
    throw "Authenticode signing failed"
}
& $signtool verify /pa /all /v $Path
if ($LASTEXITCODE -ne 0) {
    throw "Authenticode verification failed"
}

$signature = Get-AuthenticodeSignature -FilePath $Path
$actual = Get-CertificateSha256 $signature.SignerCertificate
if ($signature.Status -ne "Valid" -or $actual -ne $expected) {
    throw "Authenticode identity does not match the pinned certificate"
}

Write-Host "SIGNATURE_OK $Path"
