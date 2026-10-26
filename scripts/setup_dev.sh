#!/bin/bash
# Setup script for py-libp2p development environment (Linux / macOS).
# Installs dependency-groups via uv (preferred) or pip, after checking system
# prerequisites and selecting a supported Python from pyproject.toml.

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Avoid depending on external `dirname` so PATH-restricted prereq checks still work.
_SETUP_SRC="${BASH_SOURCE[0]}"
SCRIPT_DIR="${_SETUP_SRC%/*}"
if [[ "${SCRIPT_DIR}" == "${_SETUP_SRC}" ]]; then
    SCRIPT_DIR="."
fi
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

# Security: eMudhra/emSign CA incident (October 2026). See Discussion #1570.
MIN_UV_VERSION="0.13.4"
MIN_PIP_VERSION="26.2.2"

FORCE_PIP=0
SKIP_PRE_COMMIT=0
SKIP_SYSTEM_CHECKS=0
PYTHON_OVERRIDE=""

usage() {
    cat <<'EOF'
Usage: ./scripts/setup_dev.sh [options]

Set up a py-libp2p development environment (Linux / macOS).

Options:
  -h, --help              Show this help and exit
  --python VERSION        Force a Python version (e.g. 3.12 or 3.12.12).
                          Must be in the supported set from pyproject.toml.
  --pip                   Force the pip install path even if uv is available
  --skip-pre-commit       Do not run pre-commit install
  --skip-system-checks    Skip cmake/pkg-config/GMP checks (not recommended)

Python selection (default):
  Parse requires-python and Programming Language :: Python :: 3.X classifiers
  from pyproject.toml. Use the intersection as the supported set (today:
  3.10–3.13). Pick the newest installed interpreter in that set.

System prerequisites (checked before install):
  Linux:  sudo apt-get install cmake pkg-config libgmp-dev
  macOS:  brew install cmake pkgconfig gmp

Also requires patched tooling after the eMudhra/emSign CA incident:
  uv >= 0.13.4, pip >= 26.2.2 (see Discussion #1570).

Windows: use scripts/setup_dev.ps1 instead.
EOF
}

version_ge() {
    python3 -c '
import sys

def parts(version: str):
    out = []
    for part in version.split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        if digits:
            out.append(int(digits))
    return tuple(out)

actual, minimum = parts(sys.argv[1]), parts(sys.argv[2])
sys.exit(0 if actual >= minimum else 1)
' "$1" "$2"
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -h|--help)
                usage
                exit 0
                ;;
            --python)
                [[ $# -ge 2 ]] || { echo -e "${RED}--python requires a VERSION${NC}" >&2; exit 1; }
                PYTHON_OVERRIDE="$2"
                shift 2
                ;;
            --pip)
                FORCE_PIP=1
                shift
                ;;
            --skip-pre-commit)
                SKIP_PRE_COMMIT=1
                shift
                ;;
            --skip-system-checks)
                SKIP_SYSTEM_CHECKS=1
                shift
                ;;
            *)
                echo -e "${RED}Unknown option: $1${NC}" >&2
                usage >&2
                exit 1
                ;;
        esac
    done
}

check_system_prereqs() {
    if [[ "${SKIP_SYSTEM_CHECKS}" -eq 1 ]]; then
        echo -e "${YELLOW}Skipping system prerequisite checks${NC}"
        return 0
    fi

    echo "Checking system prerequisites..."
    local missing=0
    local cmake_bin pkg_bin

    if cmake_bin="$(command -v cmake 2>/dev/null)"; then
        echo -e "  cmake:      ${GREEN}OK${NC} (${cmake_bin})"
    else
        echo -e "  cmake:      ${RED}MISSING${NC}"
        missing=1
    fi
    if pkg_bin="$(command -v pkg-config 2>/dev/null)"; then
        echo -e "  pkg-config: ${GREEN}OK${NC} (${pkg_bin})"
    else
        echo -e "  pkg-config: ${RED}MISSING${NC}"
        missing=1
    fi
    if [[ "${missing}" -eq 0 ]] && pkg-config --exists gmp 2>/dev/null; then
        echo -e "  GMP:        ${GREEN}OK${NC} (pkg-config gmp)"
    else
        # Only blame GMP when pkg-config itself is present; otherwise the
        # missing pkg-config line above already explains the failure.
        if command -v pkg-config >/dev/null 2>&1; then
            echo -e "  GMP:        ${RED}MISSING${NC} (pkg-config gmp)"
            missing=1
        fi
    fi

    if [[ "${missing}" -ne 0 ]]; then
        echo
        if [[ "$(uname -s)" == "Darwin" ]]; then
            echo -e "${YELLOW}Install with Homebrew:${NC}"
            echo "  brew install cmake pkgconfig gmp"
        else
            echo -e "${YELLOW}Install on Debian/Ubuntu:${NC}"
            echo "  sudo apt-get install cmake pkg-config libgmp-dev"
        fi
        echo "See docs/contributing.rst (Prerequisites)."
        exit 1
    fi
}

# Print supported majors as lines: 3.10\n3.11\n...  Prefer classifiers ∩ requires-python.
supported_python_minors() {
    python3 - <<'PY'
import re
import sys
from pathlib import Path

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib  # type: ignore
    except ImportError:
        tomllib = None

text = Path("pyproject.toml").read_text(encoding="utf-8")
requires = ">=3.10,<4.0"
classifiers: list[str] = []

if tomllib is not None:
    data = tomllib.loads(text)
    project = data.get("project", {})
    requires = project.get("requires-python", requires)
    classifiers = list(project.get("classifiers", []))
else:
    m = re.search(r'requires-python\s*=\s*"([^"]+)"', text)
    if m:
        requires = m.group(1)
    classifiers = re.findall(
        r'Programming Language :: Python :: (3\.\d+)', text
    )

def parse_requires(spec: str):
    """Return (min_tuple, max_exclusive_tuple_or_None) for simple >=X,<Y forms."""
    min_v = (3, 10)
    max_v = None
    for part in spec.replace(" ", "").split(","):
        if part.startswith(">="):
            nums = tuple(int(x) for x in part[2:].split(".")[:2])
            min_v = nums + (0,) * (2 - len(nums))
        elif part.startswith(">"):
            nums = [int(x) for x in part[1:].split(".")[:2]]
            # exclusive lower bound -> bump patch conceptually by using next minor approx
            if len(nums) == 1:
                min_v = (nums[0], 0)
            else:
                min_v = (nums[0], nums[1] + 1)
        elif part.startswith("<="):
            nums = tuple(int(x) for x in part[2:].split(".")[:2])
            max_v = (nums[0], nums[1] + 1)
        elif part.startswith("<"):
            nums = tuple(int(x) for x in part[1:].split(".")[:2])
            max_v = nums + (0,) * (2 - len(nums))
    return min_v, max_v

min_v, max_v = parse_requires(requires)

minors: list[tuple[int, int]] = []
for c in classifiers:
    m = re.search(r"Python :: (3)\.(\d+)$", c) if isinstance(c, str) else None
    if m is None and isinstance(c, str) and re.fullmatch(r"3\.\d+", c):
        major, minor = 3, int(c.split(".")[1])
    elif m:
        major, minor = int(m.group(1)), int(m.group(2))
    else:
        # classifier list from regex path already "3.X"
        if isinstance(c, str) and re.fullmatch(r"3\.\d+", c):
            major, minor = 3, int(c.split(".")[1])
        else:
            continue
    ver = (major, minor)
    if ver < min_v[:2]:
        continue
    if max_v is not None and ver >= max_v[:2]:
        continue
    minors.append(ver)

# Fallback if no classifiers matched: 3.10 .. max_exclusive-1 or 3.13
if not minors:
    end = (max_v[1] - 1) if max_v and max_v[0] == 3 else 13
    start = min_v[1] if min_v[0] == 3 else 10
    minors = [(3, m) for m in range(start, end + 1)]

for major, minor in sorted(set(minors)):
    print(f"{major}.{minor}")
PY
}

find_python_bin() {
    local ver="$1"  # e.g. 3.12 or 3.12.1
    local major_minor candidate
    major_minor="$(echo "${ver}" | cut -d. -f1,2)"

    # Prefer system / uv-managed interpreters over an existing repo .venv.
    if candidate="$(command -v "python${major_minor}" 2>/dev/null)"; then
        if [[ "${candidate}" != *"/py-libp2p/.venv/"* && "${candidate}" != *"/.venv/bin/"* ]]; then
            echo "${candidate}"
            return 0
        fi
    fi
    for candidate in "/usr/bin/python${major_minor}" "/usr/local/bin/python${major_minor}"; do
        if [[ -x "${candidate}" ]]; then
            echo "${candidate}"
            return 0
        fi
    done
    if command -v uv >/dev/null 2>&1; then
        local found
        if found="$(uv python find "${major_minor}" 2>/dev/null)"; then
            echo "${found}"
            return 0
        fi
    fi
    if candidate="$(command -v "python${major_minor}" 2>/dev/null)"; then
        echo "${candidate}"
        return 0
    fi
    return 1
}

resolve_python() {
    local supported candidates=()
    mapfile -t supported < <(supported_python_minors)

    if [[ -n "${PYTHON_OVERRIDE}" ]]; then
        local ov_mm
        ov_mm="$(echo "${PYTHON_OVERRIDE}" | cut -d. -f1,2)"
        local ok=0
        for s in "${supported[@]}"; do
            if [[ "${s}" == "${ov_mm}" ]]; then
                ok=1
                break
            fi
        done
        if [[ "${ok}" -eq 0 ]]; then
            echo -e "${RED}--python ${PYTHON_OVERRIDE} is outside supported set: ${supported[*]}${NC}" >&2
            exit 1
        fi
        if ! PY_BIN="$(find_python_bin "${PYTHON_OVERRIDE}")"; then
            echo -e "${RED}Python ${PYTHON_OVERRIDE} not found on PATH / uv${NC}" >&2
            exit 1
        fi
        PY_VER="${ov_mm}"
        echo -e "${GREEN}Selected Python ${PY_VER} (${PY_BIN}) via --python${NC}"
        return 0
    fi

    if [[ -n "${UV_PYTHON:-}" ]]; then
        local ov_mm ok=0
        ov_mm="$(echo "${UV_PYTHON}" | cut -d. -f1,2)"
        for s in "${supported[@]}"; do
            [[ "${s}" == "${ov_mm}" ]] && ok=1 && break
        done
        if [[ "${ok}" -eq 0 ]]; then
            echo -e "${RED}UV_PYTHON=${UV_PYTHON} is outside supported set: ${supported[*]}${NC}" >&2
            exit 1
        fi
        if ! PY_BIN="$(find_python_bin "${UV_PYTHON}")"; then
            echo -e "${RED}UV_PYTHON=${UV_PYTHON} not found${NC}" >&2
            exit 1
        fi
        PY_VER="${ov_mm}"
        echo -e "${GREEN}Selected Python ${PY_VER} (${PY_BIN}) via UV_PYTHON${NC}"
        return 0
    fi

    # Newest first
    local s
    for ((i = ${#supported[@]} - 1; i >= 0; i--)); do
        s="${supported[$i]}"
        if PY_BIN="$(find_python_bin "${s}")"; then
            PY_VER="${s}"
            echo -e "${GREEN}Selected Python ${PY_VER} (${PY_BIN})${NC}"
            return 0
        fi
    done

    echo -e "${RED}No supported Python installed. Need one of: ${supported[*]}${NC}" >&2
    echo "Install e.g. python3.13 or: uv python install 3.13" >&2
    exit 1
}

ensure_uv() {
    if ! command -v uv >/dev/null 2>&1; then
        return 1
    fi
    local uv_version
    uv_version="$(uv --version | awk '{print $2}')"
    if ! version_ge "${uv_version}" "${MIN_UV_VERSION}"; then
        echo -e "${YELLOW}uv ${uv_version} is below ${MIN_UV_VERSION}; upgrading...${NC}"
        UV_SYSTEM_CERTS=true uv self update || {
            echo -e "${RED}Could not upgrade uv. Reinstall: curl -LsSf https://astral.sh/uv/install.sh | sh${NC}"
            exit 1
        }
    fi
    return 0
}

run_uv_setup() {
    echo -e "${GREEN}Using uv for installation (recommended)...${NC}"
    if [[ "$(uname -s)" == "Darwin" ]]; then
        CFLAGS="$(pkg-config --cflags gmp)" LDFLAGS="$(pkg-config --libs gmp)" \
            uv sync --python "${PY_VER}" --group dev
    else
        uv sync --python "${PY_VER}" --group dev
    fi
    if [[ "${SKIP_PRE_COMMIT}" -eq 0 ]]; then
        echo -e "${GREEN}Installing pre-commit hooks...${NC}"
        uv run pre-commit install
    fi
}

run_pip_setup() {
    echo -e "${GREEN}Using pip for installation...${NC}"
    if [[ -z "${VIRTUAL_ENV:-}" ]]; then
        if [[ ! -d .venv ]]; then
            echo -e "${YELLOW}Creating virtual environment with ${PY_BIN}...${NC}"
            "${PY_BIN}" -m venv .venv
        fi
        # shellcheck disable=SC1091
        source .venv/bin/activate
    fi

    local pip_version
    pip_version="$(python -m pip --version | awk '{print $2}')"
    if ! version_ge "${pip_version}" "${MIN_PIP_VERSION}"; then
        echo -e "${YELLOW}pip ${pip_version} is below ${MIN_PIP_VERSION}; upgrading...${NC}"
        python -m pip install --upgrade "pip>=${MIN_PIP_VERSION}"
    fi

    if [[ "$(uname -s)" == "Darwin" ]]; then
        CFLAGS="$(pkg-config --cflags gmp)" LDFLAGS="$(pkg-config --libs gmp)" \
            pip install --group dev -e .
    else
        pip install --group dev -e .
    fi

    if [[ "${SKIP_PRE_COMMIT}" -eq 0 ]]; then
        echo -e "${GREEN}Installing pre-commit hooks...${NC}"
        pre-commit install
    fi
}

main() {
    parse_args "$@"
    echo -e "${GREEN}Setting up py-libp2p development environment...${NC}"
    check_system_prereqs
    resolve_python

    if [[ "${FORCE_PIP}" -eq 0 ]] && ensure_uv; then
        run_uv_setup
    else
        if [[ "${FORCE_PIP}" -eq 0 ]]; then
            echo -e "${YELLOW}uv not found; falling back to pip${NC}"
        fi
        run_pip_setup
    fi

    echo -e "${GREEN}Setup complete! Run 'make pr' to check changes, or 'make docs' to build docs.${NC}"
    echo -e "Activate with: ${YELLOW}. .venv/bin/activate${NC}"
}

main "$@"
