@echo off
rem Builds fss_ao_copy.dll into fss_blender_tools\lib\ao_copy\windows-x64 (MSVC, x64, static C runtime).
rem On the maintainer's PC through the CPU cap (one compiler process, no /MP):
rem   C:\Users\uray\.claude\tools\cpucap\cpucap.exe 50 cmd /c native\ao_copy\build.cmd
rem /fp:precise and no /arch:AVX2: no FMA contraction, so the results stay bit-identical to the numpy copy.
setlocal
set "HERE=%~dp0"
set "OUT=%HERE%..\..\fss_blender_tools\lib\ao_copy\windows-x64"
set "OBJ=%HERE%build"
if not defined VCINSTALLDIR (
    call "C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat" >nul || exit /b 1
)
if not exist "%OUT%" mkdir "%OUT%"
if not exist "%OBJ%" mkdir "%OBJ%"
cl /nologo /O2 /fp:precise /MT /EHsc /std:c++17 /W4 /WX /DNDEBUG /LD "%HERE%fss_ao_copy.cpp" /Fo"%OBJ%\\" ^
    /Fe"%OUT%\fss_ao_copy.dll" /link /NOLOGO /INCREMENTAL:NO /IMPLIB:"%OBJ%\fss_ao_copy.lib" || exit /b 1
echo built %OUT%\fss_ao_copy.dll
