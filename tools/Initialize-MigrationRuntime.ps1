$MigrationRootText = git rev-parse --show-toplevel
if ($LASTEXITCODE -ne 0) {
    throw "Unable to resolve the migration repository root"
}

$MigrationRoot = [System.IO.Path]::GetFullPath($MigrationRootText.Trim())
$ExpectedMigrationRoot = [System.IO.Path]::GetFullPath(
    "D:\codes\babeldoc-minimal-migration"
)
if (-not $MigrationRoot.Equals(
    $ExpectedMigrationRoot,
    [System.StringComparison]::OrdinalIgnoreCase
)) {
    throw "Unexpected migration repository root: $MigrationRoot"
}
Set-Location -LiteralPath $MigrationRoot

$RuntimeRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $MigrationRoot ".runtime")
)

$env:UV_CACHE_DIR = Join-Path $RuntimeRoot "uv-cache"
$env:BABELDOC_CACHE_DIR = Join-Path $RuntimeRoot "babeldoc-cache"
$env:TEMP = Join-Path $RuntimeRoot "temp"
$env:TMP = $env:TEMP

foreach ($RuntimePath in @(
    $env:UV_CACHE_DIR,
    $env:BABELDOC_CACHE_DIR,
    $env:TEMP,
    $env:TMP
)) {
    $ResolvedRuntimePath = [System.IO.Path]::GetFullPath($RuntimePath)
    if (-not $ResolvedRuntimePath.StartsWith(
        $RuntimeRoot + [System.IO.Path]::DirectorySeparatorChar,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Runtime path escapes .runtime: $ResolvedRuntimePath"
    }
    New-Item -ItemType Directory -Force -Path $ResolvedRuntimePath | Out-Null
}
