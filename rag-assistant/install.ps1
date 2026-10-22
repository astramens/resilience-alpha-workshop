param([string]$ProjectRoot = (Get-Location).Path)
$ErrorActionPreference = 'Stop'
function Invoke-Docker {
    param([string[]]$DockerArgs)
    & docker @DockerArgs
    if ($LASTEXITCODE -ne 0) { throw "Docker a echoue. Installation arretee : $($DockerArgs -join ' ')" }
}
$project = (Resolve-Path -LiteralPath $ProjectRoot).Path
if (-not (Test-Path -LiteralPath (Join-Path $project 'docker-compose.yml'))) { throw 'Lancer depuis la racine du projet REARM.' }
$target = Join-Path $project 'rag-assistant'
if (Test-Path -LiteralPath $target) { throw 'Le dossier rag-assistant existe deja. Aucun fichier ecrase. Envoyer le message pour reprendre.' }
$running = & docker inspect --format '{{.State.Running}}' rearm-ollama
if ($LASTEXITCODE -ne 0 -or "$running".Trim() -ne 'true') { throw 'Le conteneur rearm-ollama doit etre demarre.' }
# Pulls happen before attaching the private network. Existing bridge keeps download connectivity.
Invoke-Docker -DockerArgs @('exec','rearm-ollama','ollama','pull','qwen2.5:1.5b')
Invoke-Docker -DockerArgs @('exec','rearm-ollama','ollama','pull','nomic-embed-text:v1.5')
$allowed = @('REPRISE_REARM.md','ANSIBLE_REARM.md','SUPERVISION_REARM.md','HTTPS_REARM.md','JOURNAUX_REARM.md')
$selected = @($allowed | Where-Object { Test-Path -LiteralPath (Join-Path $project $_) })
if ($selected.Count -lt 2) { throw 'Moins de deux procedures REARM trouvees.' }
New-Item -ItemType Directory -Path (Join-Path $target 'docs') -Force | Out-Null
foreach ($file in @('app.py','Dockerfile','requirements.txt','compose.yaml','.dockerignore','README.md','RECETTE.md','install.ps1')) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $file) -Destination $target
}
foreach ($file in $selected) { Copy-Item -LiteralPath (Join-Path $project $file) -Destination (Join-Path $target 'docs') }
$networks = & docker network ls --format '{{.Name}}'
if ($LASTEXITCODE -ne 0) { throw 'Impossible de lire les reseaux Docker.' }
if (@($networks) -notcontains 'rearm-rag-local') {
    Invoke-Docker -DockerArgs @('network','create','--internal','--label','rearm.rag=local','rearm-rag-local')
} else {
    $private = & docker network inspect --format '{{.Internal}}' rearm-rag-local
    if ($LASTEXITCODE -ne 0 -or "$private".Trim() -ne 'true') { throw 'Le reseau existant rearm-rag-local doit etre interne.' }
}
$attached = & docker inspect --format '{{json .NetworkSettings.Networks}}' rearm-ollama
if ($LASTEXITCODE -ne 0) { throw 'Impossible de lire le reseau Ollama.' }
if (-not (($attached | ConvertFrom-Json).PSObject.Properties.Name -contains 'rearm-rag-local')) {
    Invoke-Docker -DockerArgs @('network','connect','rearm-rag-local','rearm-ollama')
}
Push-Location $target
try {
    Invoke-Docker -DockerArgs @('compose','config','--quiet')
    Invoke-Docker -DockerArgs @('compose','up','-d','--build')
    Invoke-Docker -DockerArgs @('compose','ps')
} finally { Pop-Location }
Write-Host 'ASSISTANT DEMARRE : http://localhost:8501'
Write-Host 'La premiere ouverture indexe les procedures. Realiser ensuite les questions de RECETTE.md.'
Write-Host 'La recette RAG reste a valider. Aucun test offensif ni redemarrage REARM lance.'
