@echo off
rem Builds fss_uv_pack.dll into fss_blender_tools\lib\uv_pack\windows-x64 (MSVC, x64, static C runtime).
rem On the maintainer's PC through the CPU cap (one compiler process, no /MP):
rem   C:\Users\uray\.claude\tools\cpucap\cpucap.exe 50 cmd /c native\uv_pack\build.cmd
rem /fp:precise and no /arch:AVX2: no FMA contraction, so the layouts stay equal to the Python code's.
setlocal
set "HERE=%~dp0"
set "OUT=%HERE%..\..\fss_blender_tools\lib\uv_pack\windows-x64"
set "OBJ=%HERE%build"
if not defined VCINSTALLDIR (
    call "C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat" >nul || exit /b 1
)
if not exist "%OUT%" mkdir "%OUT%"
if not exist "%OBJ%" mkdir "%OBJ%"
cl /nologo /O2 /fp:precise /MT /EHsc /std:c++17 /W4 /WX /DNDEBUG /LD "%HERE%fss_uv_pack.cpp" /Fo"%OBJ%\\" ^
    /Fe"%OUT%\fss_uv_pack.dll" /link /NOLOGO /INCREMENTAL:NO /IMPLIB:"%OBJ%\fss_uv_pack.lib" || exit /b 1
echo built %OUT%\fss_uv_pack.dll
