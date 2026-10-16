@echo off
rem Deploys the add-ons to the Blender installs listed in deploy.local.json; arguments are passed on to deploy.ps1
rem (for example: deploy.bat -DryRun, deploy.bat -Force, deploy.bat -Addons fss_blender_tools).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy.ps1" %*
