#!/usr/bin/env bash
set -euo pipefail

workflow_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
prefix=${RAPTOR_BOOTSTRAP_DIR:-"$workflow_dir/.raptor-bin"}
version=2.0.16
source_url=https://download.librdf.org/source/raptor2-2.0.16.tar.gz
source_sha256=089db78d7ac982354bdbf39d973baf09581e6904ac4c92a98c5caadb3de44680
rapper="$prefix/bin/rapper"

if [[ -x "$rapper" ]]; then
  observed=$($rapper --version 2>&1 | head -n 1)
  if [[ "$observed" != "$version" ]]; then
    printf 'refusing non-matching cached Raptor at %s: %s\n' \
      "$rapper" "$observed" >&2
    exit 65
  fi
  printf 'PASS: Raptor rapper %s available at %s\n' "$version" "$rapper"
  exit 0
fi

if [[ -e "$prefix" ]] && [[ -n "$(find "$prefix" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
  printf 'refusing incomplete Raptor bootstrap directory: %s\n' "$prefix" >&2
  exit 73
fi

for command in curl tar make cc sha256sum; do
  if ! command -v "$command" >/dev/null 2>&1; then
    printf '%s is required to build Raptor %s\n' "$command" "$version" >&2
    exit 69
  fi
done

temporary=$(mktemp -d)
trap 'rm -rf "$temporary"' EXIT
archive="$temporary/raptor2-$version.tar.gz"
curl -fsSL "$source_url" -o "$archive"
printf '%s  %s\n' "$source_sha256" "$archive" | sha256sum -c -
tar -xzf "$archive" -C "$temporary"
mkdir -p "$temporary/build" "$prefix"

build_jobs=${RAPTOR_BUILD_JOBS:-$(getconf _NPROCESSORS_ONLN 2>/dev/null || printf '1')}
if ((build_jobs > 16)); then
  build_jobs=16
fi

(
  cd "$temporary/build"
  "$temporary/raptor2-$version/configure" \
    --prefix="$prefix" \
    --enable-parsers=turtle \
    --with-www=none \
    --with-yajl=no \
    --disable-gtk-doc
  make -j"$build_jobs"
  make install
)

observed=$($rapper --version 2>&1 | head -n 1)
if [[ "$observed" != "$version" ]]; then
  printf 'Raptor bootstrap produced %s, expected %s\n' \
    "$observed" "$version" >&2
  exit 65
fi
printf 'PASS: built Raptor rapper %s at %s\n' "$version" "$rapper"
