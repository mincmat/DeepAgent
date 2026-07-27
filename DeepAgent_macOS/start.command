#!/bin/bash
# DeepAgent — macOS Launcher
# This script checks and installs dependencies, then starts the bridge.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BRIDGE="$SCRIPT_DIR/bridge_server.py"

# ── Colores ──────────────────────────────────────────────────
BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo ""
echo -e "${BOLD}${CYAN}  ╔══════════════════════════════════════════╗${NC}"
echo -e "${BOLD}${CYAN}  ║        DeepAgent — macOS Edition        ║${NC}"
echo -e "${BOLD}${CYAN}  ╚══════════════════════════════════════════╝${NC}"
echo ""

# ── Verificar Python 3 ───────────────────────────────────────
PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        VER=$("$cmd" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+')
        MAJOR="${VER%%.*}"
        if [ "$MAJOR" -ge 3 ]; then
            PYTHON="$cmd"
            echo -e "${GREEN}✓ Python $VER encontrado: $cmd${NC}"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo -e "${YELLOW}⚠ Python 3 is not installed.${NC}"
    echo ""
    echo "Choose how to install Python:"
    echo "  1) Install with Homebrew (recommended)"
    echo "  2) Install Xcode Command Line Tools (includes Python 3)"
    echo "  3) Exit — I'll install Python manually"
    echo ""
    read -p "Option [1-3]: " opt

    case "$opt" in
        1)
            if command -v brew &>/dev/null; then
                echo -e "${YELLOW}Instalando Python 3 con Homebrew...${NC}"
                brew install python@3
            else
                echo -e "${YELLOW}Homebrew not installed. Installing Homebrew first...${NC}"
                /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
                echo -e "${YELLOW}Instalando Python 3...${NC}"
                brew install python@3
            fi
            PYTHON="python3"
            ;;
        2)
            echo -e "${YELLOW}Instalando Xcode Command Line Tools...${NC}"
            xcode-select --install
            echo -e "${YELLOW}Wait for the installation to finish and run this script again.${NC}"
            read -p "Press Enter to exit..."
            exit 0
            ;;
        3)
            echo -e "${YELLOW}Download Python from https://python.org and run this script again.${NC}"
            read -p "Press Enter to exit..."
            exit 0
            ;;
        *)
            echo -e "${RED}Invalid option. Exiting.${NC}"
            exit 1
            ;;
    esac

    # Verificar que se instaló
    if ! command -v "$PYTHON" &>/dev/null; then
        echo -e "${RED}✗ Could not install Python 3. Install it manually and run again.${NC}"
        read -p "Press Enter to exit..."
        exit 1
    fi
fi

# ── Verificar puerto 8765 ─────────────────────────────────────
if lsof -i :8765 &>/dev/null 2>&1; then
    echo -e "${YELLOW}⚠ Port 8765 already in use. Is another DeepAgent already running?${NC}"
    echo -e "${YELLOW}  Close it first or use another port.${NC}"
    read -p "Press Enter to exit..."
    exit 1
fi

# ── Lanzar bridge ─────────────────────────────────────────────
echo ""
echo -e "${GREEN}✓ Todas las dependencias listas${NC}"
echo -e "${CYAN}  Iniciando bridge en http://localhost:8765 ...${NC}"
echo -e "${CYAN}  Keep this window open while using the extension.${NC}"
echo -e "${CYAN}  Close it with Ctrl+C when done.${NC}"
echo ""

$PYTHON "$BRIDGE"

# ── Al salir ──────────────────────────────────────────────────
echo ""
echo -e "${YELLOW}DeepAgent detenido.${NC}"
read -p "Press Enter to close this window..."
