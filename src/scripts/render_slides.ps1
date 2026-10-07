# Render every slide of the deck to PNG with the locally installed PowerPoint (COM), for visual QA.
# Usage: powershell -ExecutionPolicy Bypass -File scripts\render_slides.ps1 [-Deck <pptx>] [-Out <dir>]
param(
    [string]$Deck = (Join-Path $PSScriptRoot "..\docs\presentation\Risk_Signal_Engine.pptx"),
    [string]$Out = (Join-Path $PSScriptRoot "..\docs\presentation\preview")
)
$ErrorActionPreference = "Stop"
$Deck = (Resolve-Path -LiteralPath $Deck).Path
New-Item -ItemType Directory -Force -Path $Out | Out-Null
$Out = (Resolve-Path -LiteralPath $Out).Path
Get-ChildItem -LiteralPath $Out -Filter "slide-*.png" | Remove-Item -Force
$ppt = New-Object -ComObject PowerPoint.Application
try {
    # Open(FileName, ReadOnly, Untitled, WithWindow)
    $pres = $ppt.Presentations.Open($Deck, -1, 0, 0)
    $i = 0
    foreach ($slide in $pres.Slides) {
        $i++
        $slide.Export((Join-Path $Out ("slide-{0}.png" -f $i)), "PNG", 1920, 1080)
    }
    $pres.Close()
    Write-Output "rendered $i slides to $Out"
} finally {
    $ppt.Quit()
    [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($ppt)
}
