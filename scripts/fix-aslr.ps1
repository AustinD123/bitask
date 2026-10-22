# Lowers vm.mmap_rnd_bits inside the Docker Desktop WSL2 VM kernel.
# Needed when TSan fails with "unexpected memory mapping" (high ASLR entropy).
# The setting is not persistent: it resets when Docker Desktop restarts, so
# re-run this script after each restart. Requires Docker Desktop to be running.
$ErrorActionPreference = 'Stop'
docker run --rm --privileged ubuntu:24.04 sysctl -w vm.mmap_rnd_bits=28
if ($LASTEXITCODE -ne 0) { throw "sysctl failed with exit code $LASTEXITCODE" }
