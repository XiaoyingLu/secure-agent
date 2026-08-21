#!/usr/bin/env pwsh

param(
    [Parameter(Mandatory = $true)]
    [string]$SubscriptionId,

    [Parameter(Mandatory = $true)]
    [string]$ResourceGroup,

    [Parameter(Mandatory = $true)]
    [string]$AcrName,

    [string]$ImageRepository = "secure-agent",

    [string]$ImageTag = "",

    [switch]$CreateAcr,

    [switch]$UseAcrBuild
)

$ErrorActionPreference = "Stop"

function Test-CommandExists {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Invoke-External {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Executable,

        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,

        [string]$ErrorMessage = "External command failed"
    )

    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$ErrorMessage (exit code $LASTEXITCODE)"
    }
}

if ($AcrName -notmatch '^[a-z0-9]{5,50}$') {
    throw "AcrName '$AcrName' is invalid. Use 5-50 lowercase alphanumeric characters only (no hyphens)."
}

if (-not (Test-CommandExists -Name "az")) {
    throw "Azure CLI 'az' is not installed or not on PATH. Install Azure CLI and retry."
}

if (-not $UseAcrBuild -and -not (Test-CommandExists -Name "docker")) {
    throw "Docker CLI is not installed or not on PATH. Install Docker Desktop and retry, or rerun with -UseAcrBuild."
}

if (-not $ImageTag) {
    $ImageTag = (Get-Date).ToString("yyyyMMdd.HHmmss")
}

$acrLoginServer = "$AcrName.azurecr.io"
$localTag = "$ImageRepository`:local"
$latestTag = "$acrLoginServer/$ImageRepository`:latest"
$versionTag = "$acrLoginServer/$ImageRepository`:$ImageTag"

Write-Host "Setting Azure subscription to $SubscriptionId"
Invoke-External -Executable "az" -Arguments @("account", "set", "--subscription", $SubscriptionId) -ErrorMessage "Failed to set Azure subscription"

$acrExists = $true
& az acr show --name $AcrName --resource-group $ResourceGroup | Out-Null
if ($LASTEXITCODE -ne 0) {
    $acrExists = $false
}

if (-not $acrExists) {
    if (-not $CreateAcr) {
        throw "ACR '$AcrName' does not exist in '$ResourceGroup'. Rerun with -CreateAcr to provision it."
    }

    Write-Host "Creating Azure Container Registry $AcrName in $ResourceGroup"
    Invoke-External -Executable "az" -Arguments @("acr", "create", "--name", $AcrName, "--resource-group", $ResourceGroup, "--sku", "Standard", "--admin-enabled", "false") -ErrorMessage "Failed to create ACR"
}

if ($UseAcrBuild) {
    Write-Host "Building and pushing image remotely with ACR Tasks"
    Invoke-External -Executable "az" -Arguments @("acr", "build", "--registry", $AcrName, "--image", "$ImageRepository`:latest", "--image", "$ImageRepository`:$ImageTag", ".") -ErrorMessage "ACR build failed"
}
else {
    Write-Host "Building local container image $localTag"
    Invoke-External -Executable "docker" -Arguments @("build", "-t", $localTag, ".") -ErrorMessage "Docker build failed"

    Write-Host "Logging in to ACR $AcrName"
    Invoke-External -Executable "az" -Arguments @("acr", "login", "--name", $AcrName) -ErrorMessage "ACR login failed"

    Write-Host "Tagging images"
    Invoke-External -Executable "docker" -Arguments @("tag", $localTag, $latestTag) -ErrorMessage "Failed to tag latest image"
    Invoke-External -Executable "docker" -Arguments @("tag", $localTag, $versionTag) -ErrorMessage "Failed to tag versioned image"

    Write-Host "Pushing $latestTag"
    Invoke-External -Executable "docker" -Arguments @("push", $latestTag) -ErrorMessage "Failed to push latest tag"

    Write-Host "Pushing $versionTag"
    Invoke-External -Executable "docker" -Arguments @("push", $versionTag) -ErrorMessage "Failed to push versioned tag"
}

Write-Host "Validating pushed tags"
Invoke-External -Executable "az" -Arguments @("acr", "repository", "show-tags", "--name", $AcrName, "--repository", $ImageRepository, "--orderby", "time_desc", "--top", "10", "--output", "table") -ErrorMessage "Failed to validate pushed tags"

Write-Host "Publish complete"
Write-Host "Latest image: $latestTag"
Write-Host "Versioned image: $versionTag"
