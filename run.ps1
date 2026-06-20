param(
    [string]$topic = "Enron",
    [switch]$template,
    [switch]$quick,
    [string]$extra = ""
)
$py = "C:\Users\A Center\AppData\Local\Programs\Python\Python314\python.exe"
$root = "C:\Users\A Center\OneDrive\المستندات\mindmargin"
$t = if ($template) { "--template" } else { "" }
$q = if ($quick) { "--quick" } else { "" }
Set-Location -LiteralPath $root
& $py -c "import sys; sys.path.insert(0, r'$root'); import mindmargin.main; mindmargin.main.main()" --topic "$topic" $t $q --skip-validation $extra
