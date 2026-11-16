@echo off
rem Builds fss_ao_copy.dll into fss_blender_tools\lib\ao_copy\windows-x64 (MSVC, x64, static C runtime).
rem On the maintainer's PC through the CPU cap (one compiler process at a time, no /MP):
rem   C:\Users\uray\.claude\tools\cpucap\cpucap.exe 50 cmd /c native\ao_copy\build.cmd
rem /fp:precise and no /arch:AVX2: no FMA contraction, so the results stay bit-identical to the numpy copy.
rem zlib (native\third_party\zlib, 1.3.2, its inflate and deflate) is compiled first at its own warning level, then
rem linked in.
setlocal
set "HERE=%~dp0"
set "OUT=%HERE%..\..\fss_blender_tools\lib\ao_copy\windows-x64"
set "OBJ=%HERE%build"
set "ZLIB=%HERE%..\third_party\zlib"
if not defined VCINSTALLDIR (
    call "C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat" >nul || exit /b 1
)
if not exist "%OUT%" mkdir "%OUT%"
if not exist "%OBJ%\zlib" mkdir "%OBJ%\zlib"
cl /nologo /c /O2 /MT /W3 /DNDEBUG /D_CRT_SECURE_NO_WARNINGS "%ZLIB%\adler32.c" "%ZLIB%\crc32.c" ^
    "%ZLIB%\inflate.c" "%ZLIB%\inffast.c" "%ZLIB%\inftrees.c" "%ZLIB%\zutil.c" "%ZLIB%\deflate.c" ^
    "%ZLIB%\trees.c" /Fo"%OBJ%\zlib\\" || exit /b 1
cl /nologo /O2 /fp:precise /MT /EHsc /std:c++17 /W4 /WX /DNDEBUG /LD "%HERE%fss_ao_copy.cpp" "%HERE%fss_ao_open.cpp" ^
    "%HERE%fss_ao_png.cpp" "%HERE%fss_ao_pixels.cpp" "%HERE%fss_ao_compose.cpp" "%HERE%fss_ao_scene.cpp" "%OBJ%\zlib\adler32.obj" "%OBJ%\zlib\crc32.obj" "%OBJ%\zlib\inflate.obj" ^
    "%OBJ%\zlib\inffast.obj" "%OBJ%\zlib\inftrees.obj" "%OBJ%\zlib\zutil.obj" "%OBJ%\zlib\deflate.obj" ^
    "%OBJ%\zlib\trees.obj" /Fo"%OBJ%\\" /Fe"%OUT%\fss_ao_copy.dll" ^
    /link /NOLOGO /INCREMENTAL:NO /IMPLIB:"%OBJ%\fss_ao_copy.lib" || exit /b 1
echo built %OUT%\fss_ao_copy.dll
