<#
.SYNOPSIS
Copies a Release build of FSS OptiX (the AO Baker, aobaker.exe of F:\glider) into the add-on.

.DESCRIPTION
OptiX baker journal (docs/journal/20261114.optix-baker.md), decision 21: the baker ships in the add-on as
fss_blender_tools\lib\ao_baker\windows-x64\, like lib\jxl and lib\ao_copy, and deploy carries it from there. This script
copies from Glider's package folder:
  aobaker.exe   the baker
  oidn\         Open Image Denoise and the Visual C++ runtime it needs (Glider's ao-baker-oidn.targets puts them there)
and writes VERSION.txt beside them (Glider's commit, whether its tree had changes, the exe's time), which the add-on
records with each master the baker makes (decision 23).

Build Glider first (Release x64, aobaker.vcxproj, under the CPU cap). Files in the destination that the build does not
have are reported, not deleted.

.EXAMPLE
powershell -ExecutionPolicy Bypass -File tools\update-ao-baker.ps1
powershell -ExecutionPolicy Bypass -File tools\update-ao-baker.ps1 -Glider D:\glider -DryRun
#>
param(
    [string]$Glider = "F:\glider",
    [string]$Build = "",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$repo = Split-Path $PSScriptRoot -Parent
$dest = Join-Path $repo "fss_blender_tools\lib\ao_baker\windows-x64"
if (-not $Build) {
    $Build = Join-Path $Glider "out\bin\x64\Release"
}
$exe = Join-Path $Build "aobaker.exe"
$oidn = Join-Path $Build "oidn"
if (-not (Test-Path -LiteralPath $exe)) {
    throw "No aobaker.exe in ${Build}: build Glider's aobaker.vcxproj (Release x64) first"
}
if (-not (Test-Path -LiteralPath (Join-Path $oidn "OpenImageDenoise.dll"))) {
    throw "No oidn\OpenImageDenoise.dll in ${Build}: the build's ao-baker-oidn.targets copies it there"
}

# What is copied: the exe and every file of oidn\, by their paths under the build folder
$files = @("aobaker.exe") + @(Get-ChildItem -LiteralPath $oidn -File | ForEach-Object { "oidn\" + $_.Name })

$commit = "unknown"
$dirty = ""
try {
    $commit = (& git -C $Glider rev-parse --short HEAD 2>$null)
    if ((& git -C $Glider status --porcelain 2>$null | Measure-Object).Count -gt 0) {
        $dirty = " (with uncommitted changes)"
    }
}
catch {
    $commit = "unknown"
}
$built = (Get-Item -LiteralPath $exe).LastWriteTime.ToString("yyyy-MM-dd HH:mm:ss")
$version = "glider $commit$dirty`nbuilt $built`n"

$total = 0
foreach ($relative in $files) {
    $from = Join-Path $Build $relative
    $to = Join-Path $dest $relative
    $size = (Get-Item -LiteralPath $from).Length
    $total += $size
    $same = (Test-Path -LiteralPath $to) -and ((Get-FileHash -LiteralPath $to).Hash -eq (Get-FileHash -LiteralPath $from).Hash)
    $state = if ($same) { "same" } elseif (Test-Path -LiteralPath $to) { "update" } else { "new" }
    Write-Host ("{0,-7} {1,-40} {2,10:N1} KB" -f $state, $relative, ($size / 1KB))
    if (-not $DryRun -and -not $same) {
        New-Item -ItemType Directory -Force -Path (Split-Path $to -Parent) | Out-Null
        Copy-Item -LiteralPath $from -Destination $to -Force
    }
}
if (Test-Path -LiteralPath $dest) {
    $known = @{}
    foreach ($relative in $files) {
        $known[$relative.ToLowerInvariant()] = $true
    }
    $known["version.txt"] = $true
    Get-ChildItem -LiteralPath $dest -Recurse -File | ForEach-Object {
        $relative = $_.FullName.Substring($dest.Length + 1)
        if (-not $known.ContainsKey($relative.ToLowerInvariant())) {
            Write-Host "extra   $relative (not in the build; left in place)"
        }
    }
}
if (-not $DryRun) {
    New-Item -ItemType Directory -Force -Path $dest | Out-Null
    [System.IO.File]::WriteAllText((Join-Path $dest "VERSION.txt"), $version)
}
Write-Host ("{0} files, {1:N1} MB, from {2} ({3}){4}" -f $files.Count, ($total / 1MB), $Build, ($version -replace "`n", "; ").TrimEnd("; "),
    $(if ($DryRun) { "; dry run, nothing copied" } else { "" }))
