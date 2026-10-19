# Generates the Word fixtures with Microsoft Word (COM) from doc_spec.json (-> legacy_bold_italic.doc)
# and doc_spec_latin.json (-> legacy_latin_emphasis.doc). All text is made up.
#   powershell -File make_doc.ps1 -SpecPath doc_spec.json -Out raw_bold_italic.doc
# Word adds the machine owner's name to the file; strip it and everything unused with
#   python repack_ole.py raw_bold_italic.doc ..\legacy_bold_italic.doc WordDocument 1Table --scrub "Owner Name=Test Author."
# (the two strings given to --scrub must have the same length).
param(
    [Parameter(Mandatory = $true)][string]$SpecPath,
    [Parameter(Mandatory = $true)][string]$Out
)
$ErrorActionPreference = "Stop"
$spec = Get-Content -Raw -Encoding UTF8 $SpecPath | ConvertFrom-Json
$Out = [System.IO.Path]::GetFullPath($Out)

function Set-Run($doc, $pos, $text, $flags) {
    $r = $doc.Range($pos, $pos)
    $r.Text = $text
    $r.Font.Bold = $(if ($flags -match "b") { 1 } else { 0 })
    $r.Font.Italic = $(if ($flags -match "i") { 1 } else { 0 })
    if ($flags -eq "strong") { $r.Style = $doc.Styles.Item(-88) }
    if ($flags -eq "emph") { $r.Style = $doc.Styles.Item(-89) }
    return $r.End
}

$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
try {
    $doc = $word.Documents.Add()
    foreach ($p in $spec.paras) {
        $last = $doc.Paragraphs.Item($doc.Paragraphs.Count).Range
        $start = $last.Start
        $pos = $start
        # The paragraph style goes on first: applying one afterwards would wipe
        # the direct bold/italic of a mostly-formatted paragraph.
        if ($p.style -is [string]) {
            # A custom paragraph style that is bold itself; runs set to "plain"
            # then carry a direct "not bold" that must invert the style.
            $custom = $doc.Styles.Add($p.style, 1)
            $custom.Font.Bold = 1
            $last.ParagraphFormat.Style = $custom
        } else {
            $last.ParagraphFormat.Style = $doc.Styles.Item([int]$p.style)
        }
        foreach ($run in $p.runs) { $pos = Set-Run $doc $pos $run.t $run.f }
        $doc.Content.InsertParagraphAfter()
    }
    $last = $doc.Paragraphs.Item($doc.Paragraphs.Count).Range
    $rows = $spec.table.Count
    $cols = $spec.table[0].Count
    $tbl = $doc.Tables.Add($last, $rows, $cols)
    for ($r = 0; $r -lt $rows; $r++) {
        for ($c = 0; $c -lt $cols; $c++) {
            $cell = $spec.table[$r][$c]
            $rng = $tbl.Cell($r + 1, $c + 1).Range
            $rng.Text = $cell.t
            $rng = $tbl.Cell($r + 1, $c + 1).Range
            $rng.MoveEnd(1, -1) | Out-Null
            $rng.Font.Bold = $(if ($cell.f -match "b") { 1 } else { 0 })
            $rng.Font.Italic = $(if ($cell.f -match "i") { 1 } else { 0 })
        }
    }
    $tail = $doc.Paragraphs.Item($doc.Paragraphs.Count).Range
    $tail.InsertBefore($spec.after)
    $doc.SaveAs2($Out, 0)
    $doc.Close(0)
}
finally {
    $word.Quit()
}
Write-Output "saved $Out"
