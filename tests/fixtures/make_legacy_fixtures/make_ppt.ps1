# Generates legacy_notes.ppt with Microsoft PowerPoint (COM) from ppt_spec.json. All text is made up.
#   powershell -File make_ppt.ps1 -SpecPath ppt_spec.json -Out raw_notes.ppt
# Then drop the thumbnail and summary streams (keeps it under 100 KB):
#   python repack_ole.py raw_notes.ppt ..\legacy_notes.ppt "Current User" "PowerPoint Document"
# PowerPoint rewrites the whole file on every save, so a deck with stale notes from an
# incremental save cannot be produced this way; tests/legacy_builders.py crafts those.
param(
    [Parameter(Mandatory = $true)][string]$SpecPath,
    [Parameter(Mandatory = $true)][string]$Out
)
$ErrorActionPreference = "Stop"
$spec = Get-Content -Raw -Encoding UTF8 $SpecPath | ConvertFrom-Json
$Out = [System.IO.Path]::GetFullPath($Out)

$app = New-Object -ComObject PowerPoint.Application
try {
    $pres = $app.Presentations.Add(0)
    $index = 0
    foreach ($s in $spec.slides) {
        $index++
        $slide = $pres.Slides.Add($index, 2)   # ppLayoutText: title + bullets
        $slide.Shapes.Item(1).TextFrame.TextRange.Text = $s.title
        $slide.Shapes.Item(2).TextFrame.TextRange.Text = ($s.body -join "`r")
        if ($s.notes.Count -gt 0) {
            $slide.NotesPage.Shapes.Placeholders.Item(2).TextFrame.TextRange.Text = ($s.notes -join "`r")
        }
    }
    # Each unused slide layout is written into a .ppt as a ~17 KB master; drop
    # the ones nothing uses so the fixture stays small (the used one refuses to go).
    $layouts = $pres.SlideMaster.CustomLayouts
    for ($i = $layouts.Count; $i -ge 1; $i--) {
        try { $layouts.Item($i).Delete() } catch { }
    }
    $pres.SaveAs($Out, 1)   # ppSaveAsPresentation = the 97-2003 .ppt format
    $pres.Close()
}
finally {
    $app.Quit()
}
Write-Output "saved $Out"
