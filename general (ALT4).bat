@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul

cd /d "%~dp0"

rem --- service.bat (зависимости/обновы/фильтры) ---
call service.bat status_zapret
call service.bat check_updates
call service.bat load_game_filter
echo:

rem --- paths ---
set "BIN=%~dp0bin\\"
set "LISTS=%~dp0lists\\"
cd /d "%BIN%"

rem -----------------------------------------------------------------
rem 1) Нормализация GameFilter (убираем CR/LF, кавычки, пробелы, запятые)
rem -----------------------------------------------------------------

rem Срезаем возможный CR/LF
for /f "delims=" %%A in ('cmd /v:on /c echo(!GameFilter!') do set "GameFilter=%%A"

set "GameFilter=!GameFilter:"=!"
set "GameFilter=!GameFilter: =!"

:trimGF
if "!GameFilter:~0,1!"=="," set "GameFilter=!GameFilter:~1!" & goto trimGF
if "!GameFilter:~-1!"=="," set "GameFilter=!GameFilter:~0,-1!" & goto trimGF

rem Валидация: разрешаем только цифры/запятая/дефис
set "GF_BAD="
for /f "delims=0123456789,-," %%A in ("!GameFilter!") do set "GF_BAD=%%A"
if defined GF_BAD set "GameFilter="

rem -----------------------------------------------------------------
rem 2) Собираем wf-* (и валидируем ещё раз)
rem -----------------------------------------------------------------
set "WF_TCP_BASE=80,443,2053,2083,2087,2096,8443"
set "WF_UDP_BASE=443,19294-19344,50000-50100"

set "WF_TCP=!WF_TCP_BASE!"
set "WF_UDP=!WF_UDP_BASE!"

if defined GameFilter (
  set "WF_TCP=!WF_TCP!,!GameFilter!"
  set "WF_UDP=!WF_UDP!,!GameFilter!"
)

set "WFTCP_BAD="
for /f "delims=0123456789,-," %%A in ("!WF_TCP!") do set "WFTCP_BAD=%%A"
if defined WFTCP_BAD set "WF_TCP=!WF_TCP_BASE!"

rem (Можно убрать эти echo, если не нужны в логе MVZ)
echo GameFilter=[!GameFilter!]
echo WF_TCP=[!WF_TCP!]
echo WF_UDP=[!WF_UDP!]
echo:

rem -----------------------------------------------------------------
rem 3) Запуск winws
rem    ВАЖНО: без start, чтобы не открывалось отдельное окно
rem    и чтобы cmd/bat "держал" процесс внутри MVZ
rem -----------------------------------------------------------------

if not defined GameFilter goto RUN_NO_GAME

:RUN_WITH_GAME
"%BIN%winws.exe" --wf-tcp=!WF_TCP! --wf-udp=!WF_UDP! ^
--filter-udp=443 --hostlist="%LISTS%list-general.txt" --hostlist-exclude="%LISTS%list-exclude.txt" --ipset-exclude="%LISTS%ipset-exclude.txt" --dpi-desync=fake --dpi-desync-repeats=6 --dpi-desync-fake-quic="%BIN%quic_initial_www_google_com.bin" --new ^
--filter-udp=19294-19344,50000-50100 --filter-l7=discord,stun --dpi-desync=fake --dpi-desync-repeats=6 --new ^
--filter-tcp=2053,2083,2087,2096,8443 --hostlist-domains=discord.media --dpi-desync=fake,multisplit --dpi-desync-repeats=6 --dpi-desync-fooling=badseq --dpi-desync-badseq-increment=1000 --dpi-desync-fake-tls="%BIN%tls_clienthello_www_google_com.bin" --new ^
--filter-tcp=443 --hostlist="%LISTS%list-google.txt" --ip-id=zero --dpi-desync=fake,multisplit --dpi-desync-repeats=6 --dpi-desync-fooling=badseq --dpi-desync-badseq-increment=1000 --dpi-desync-fake-tls="%BIN%tls_clienthello_www_google_com.bin" --new ^
--filter-tcp=80,443 --hostlist="%LISTS%list-general.txt" --hostlist-exclude="%LISTS%list-exclude.txt" --ipset-exclude="%LISTS%ipset-exclude.txt" --dpi-desync=fake,multisplit --dpi-desync-repeats=6 --dpi-desync-fooling=badseq --dpi-desync-badseq-increment=1000 --dpi-desync-fake-tls="%BIN%tls_clienthello_www_google_com.bin" --new ^
--filter-udp=443 --ipset="%LISTS%ipset-all.txt" --hostlist-exclude="%LISTS%list-exclude.txt" --ipset-exclude="%LISTS%ipset-exclude.txt" --dpi-desync=fake --dpi-desync-repeats=6 --dpi-desync-fake-quic="%BIN%quic_initial_www_google_com.bin" --new ^
--filter-tcp=80,443,!GameFilter! --ipset="%LISTS%ipset-all.txt" --hostlist-exclude="%LISTS%list-exclude.txt" --ipset-exclude="%LISTS%ipset-exclude.txt" --dpi-desync=fake,multisplit --dpi-desync-repeats=6 --dpi-desync-fooling=badseq --dpi-desync-badseq-increment=1000 --dpi-desync-fake-tls="%BIN%tls_clienthello_www_google_com.bin" --new ^
--filter-udp=!GameFilter! --ipset="%LISTS%ipset-all.txt" --ipset-exclude="%LISTS%ipset-exclude.txt" --dpi-desync=fake --dpi-desync-autottl=2 --dpi-desync-repeats=10 --dpi-desync-any-protocol=1 --dpi-desync-fake-unknown-udp="%BIN%quic_initial_www_google_com.bin" --dpi-desync-cutoff=n2

exit /b %errorlevel%

:RUN_NO_GAME
"%BIN%winws.exe" --wf-tcp=!WF_TCP! --wf-udp=!WF_UDP! ^
--filter-udp=443 --hostlist="%LISTS%list-general.txt" --hostlist-exclude="%LISTS%list-exclude.txt" --ipset-exclude="%LISTS%ipset-exclude.txt" --dpi-desync=fake --dpi-desync-repeats=6 --dpi-desync-fake-quic="%BIN%quic_initial_www_google_com.bin" --new ^
--filter-udp=19294-19344,50000-50100 --filter-l7=discord,stun --dpi-desync=fake --dpi-desync-repeats=6 --new ^
--filter-tcp=2053,2083,2087,2096,8443 --hostlist-domains=discord.media --dpi-desync=fake,multisplit --dpi-desync-repeats=6 --dpi-desync-fooling=badseq --dpi-desync-badseq-increment=1000 --dpi-desync-fake-tls="%BIN%tls_clienthello_www_google_com.bin" --new ^
--filter-tcp=443 --hostlist="%LISTS%list-google.txt" --ip-id=zero --dpi-desync=fake,multisplit --dpi-desync-repeats=6 --dpi-desync-fooling=badseq --dpi-desync-badseq-increment=1000 --dpi-desync-fake-tls="%BIN%tls_clienthello_www_google_com.bin" --new ^
--filter-tcp=80,443 --hostlist="%LISTS%list-general.txt" --hostlist-exclude="%LISTS%list-exclude.txt" --ipset-exclude="%LISTS%ipset-exclude.txt" --dpi-desync=fake,multisplit --dpi-desync-repeats=6 --dpi-desync-fooling=badseq --dpi-desync-badseq-increment=1000 --dpi-desync-fake-tls="%BIN%tls_clienthello_www_google_com.bin" --new ^
--filter-udp=443 --ipset="%LISTS%ipset-all.txt" --hostlist-exclude="%LISTS%list-exclude.txt" --ipset-exclude="%LISTS%ipset-exclude.txt" --dpi-desync=fake --dpi-desync-repeats=6 --dpi-desync-fake-quic="%BIN%quic_initial_www_google_com.bin" --new ^
--filter-tcp=80,443 --ipset="%LISTS%ipset-all.txt" --hostlist-exclude="%LISTS%list-exclude.txt" --ipset-exclude="%LISTS%ipset-exclude.txt" --dpi-desync=fake,multisplit --dpi-desync-repeats=6 --dpi-desync-fooling=badseq --dpi-desync-badseq-increment=1000 --dpi-desync-fake-tls="%BIN%tls_clienthello_www_google_com.bin" --new

exit /b %errorlevel%
