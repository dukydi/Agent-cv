param([string]$Pptx, [string]$OutDir)
$ppt = New-Object -ComObject PowerPoint.Application
try {
    $pres = $ppt.Presentations.Open($Pptx, $true, $false, $false)
    if (-not (Test-Path $OutDir)) { New-Item -ItemType Directory -Path $OutDir | Out-Null }
    $pres.Slides.Item(1).Export("$OutDir\slide1.png", "PNG", 1600, 900)
    $pres.Close()
    Write-Output "PNG OK : $OutDir\slide1.png"
} finally {
    $ppt.Quit()
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($ppt) | Out-Null
}
