# Reproducible build and test environment for the verification harness.
# Pinned by digest so `ubuntu:24.04` cannot silently change under us.
# Build with: docker build -t verify-harness .
FROM ubuntu:24.04@sha256:68ee22004a9109b44973313b02ff7b1de250f1de0f5ecb628d73f579aaff33ac

ENV DEBIAN_FRONTEND=noninteractive

# clang-18 and llvm-18 (for llvm-symbolizer) provide the compiler.
# libclang-rt-18-dev provides the ASan, UBSan and TSan runtime libraries
# (libclang_rt.*.a); clang-18 alone does not pull them in.
# python3-pytest is the only pytest source: do not also pip-install it.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      clang-18 llvm-18 libclang-rt-18-dev \
      python3 python3-pip python3-pytest make bc ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# The harness reads CC/CXX from the environment and falls back to clang/clang++.
ENV CC=clang-18 \
    CXX=clang++-18 \
    ASAN_SYMBOLIZER_PATH=/usr/lib/llvm-18/bin/llvm-symbolizer \
    PYTHONDONTWRITEBYTECODE=1

# The repo is mounted read-only here (-v "$PWD":/work:ro). Workdirs go to /tmp.
WORKDIR /work
