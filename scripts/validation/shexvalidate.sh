#!/bin/bash
# scripts/validation/shexvalidate.sh
#
# Bash shim that runs ShexValidate.java in a fresh JVM with the Jena
# classpath assembled from the Groovy Grape cache. The reason for this
# detour: Groovy 2.4's ASM 5 bytecode generator can't synthesize call sites
# for Jena 4.10 classes (Java 11+ bytecode features → "Illegal type in
# constant pool" VerifyError). Running the validator out-of-process bypasses
# Groovy's MOP entirely.
#
# Usage:
#   shexvalidate.sh <graph> <shapes> <shapeMap> [--list]
# See ShexValidate.java for arg/output semantics.
#
# Prereq: a Groovy script under scripts/validation/ has previously @Grab-bed
# jena-shex 4.10.0 (the file fetch_shex_jars.groovy primes this on first
# install). After that, the classpath is just everything in ~/.groovy/grapes.
#
# Exits 0 on conform, 1 on non-conform, 2 on error (matches Java side).

set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
CP_FILE="${DIR}/.shex_classpath"

# fetch_shex_jars.groovy writes a deconflicted classpath to .shex_classpath.
# Bootstrap automatically when the cache is missing OR stale, so users don't
# have to remember the priming step.
#
# "Stale" matters because .shex_classpath holds absolute paths into a specific
# user's Groovy dependency cache. When the repository is copied to another
# host or user,
# the cached paths no longer exist and `java -cp` fails with
# "package org.apache.jena.* does not exist". Detect that by probing the first
# classpath entry and re-prime against the local Grape cache when it's gone.
cp_stale() {
    [ ! -s "$CP_FILE" ] && return 0
    local first
    first="$(head -n1 "$CP_FILE" | cut -d: -f1)"
    [ -z "$first" ] || [ ! -e "$first" ]
}
if cp_stale; then
    echo "[shexvalidate] priming classpath via fetch_shex_jars.groovy ..." >&2
    (cd "$(dirname "$DIR")/.." && groovy "${DIR}/fetch_shex_jars.groovy") >&2
fi

if [ ! -s "$CP_FILE" ]; then
    echo "ERROR could not build Jena ShEx classpath at $CP_FILE" >&2
    exit 2
fi

CLASSPATH="$(cat "$CP_FILE")"

# `java --source` (single-file source mode, JEP 330) compiles & runs
# ShexValidate.java in one step. Suppress the noisy slf4j missing-binding
# warning unless DEBUG is set.
JAVA_FLAGS="${JAVA_FLAGS:-}"
exec java $JAVA_FLAGS -cp "$CLASSPATH" "${DIR}/ShexValidate.java" "$@"
