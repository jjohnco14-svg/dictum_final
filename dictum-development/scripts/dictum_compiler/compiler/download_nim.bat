@echo off
REM Fetches and vendors the Nim compiler for the --backend nim target.
REM Normally you never need to run this yourself -- dictumc_cli.py FILE.dict
REM --backend nim --run does this automatically on first use. This script
REM exists for pre-warming a machine, or checking the install without
REM compiling anything.
setlocal
set HERE=%~dp0
python "%HERE%dictumc_cli.py" --install-nim
