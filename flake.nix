{
  description = "⛵ Test Sail - PySpark/PySail testing project";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        python = pkgs.python312;
      in {
        devShells.default = pkgs.mkShell {
          name = "test-sail";

          buildInputs = [
            python
            pkgs.jdk17
            pkgs.fzf
          ];

          shellHook = ''
            echo "⛵ Test Sail - Development environment"
            echo ""

            # Create local venv if not exists
            if [ ! -d ".venv-nix" ]; then
              echo "Creating virtual environment..."
              python -m venv .venv-nix
            fi

            source .venv-nix/bin/activate

            # Install dependencies if missing
            if ! python -c "import pysail" 2>/dev/null; then
              echo "Installing dependencies..."
              pip install --quiet --upgrade pip
              pip install --quiet pysail "pyspark[connect]" pytest ptpython ruff build colorlog &
              PIP_PID=$!

              # Sailboat animation
              WIDTH=40
              while kill -0 $PIP_PID 2>/dev/null; do
                for ((i=0; i<=WIDTH; i++)); do
                  printf "\r%*s⛵%*s" $i "" $((WIDTH-i)) ""
                  sleep 0.1
                  if ! kill -0 $PIP_PID 2>/dev/null; then break; fi
                done
              done
              printf "\r%*s\r" $((WIDTH+2)) ""
              wait $PIP_PID
            fi

            echo ""
            echo "Available backends:"
            echo "  - PySail:  SPARK_BACKEND=pysail pytest -v"
            echo "  - PySpark: SPARK_BACKEND=pyspark pytest -v"
            echo ""
            echo "Sail server:"
            echo "  sail spark server --port 50051"
            echo ""
            echo "Interactive terminal:"
            echo "  ptpython"
            echo ""
            echo "Demo:"
            echo "  python src/main.py"
            echo ""
            echo "Linter:"
            echo "  ruff check .        # Check errors"
            echo "  ruff check --fix .  # Auto-fix"
            echo "  ruff format .       # Format code"
            echo ""
            echo "Build:"
            echo "  python -m build     # Generate wheel in dist/"
            echo ""
            echo "Python: $(python --version)"
            echo "Java:   $(java -version 2>&1 | head -1)"

            export SPARK_BACKEND=pysail
            export PS1="⛵ \[\e[36m\]\W\[\e[0m\] $ "
            export PTPYTHON_CONFIG_HOME="$PWD/.ptpython"

            # fzf history search (Ctrl+R)
            eval "$(fzf --bash)"

            # Aliases
            alias t="pytest -v"
            alias ts="SPARK_BACKEND=pysail pytest -v"
            alias tp="SPARK_BACKEND=pyspark pytest -v"
            alias r="ruff check ."
            alias rf="ruff check --fix . && ruff format ."
          '';
        };

        devShells.pysail = pkgs.mkShell {
          name = "test-sail-pysail";

          buildInputs = [ python pkgs.fzf ];

          shellHook = ''
            echo "⛵ Test Sail - PySail only (no Java)"
            echo ""

            if [ ! -d ".venv-nix" ]; then
              python -m venv .venv-nix
            fi

            source .venv-nix/bin/activate

            if ! python -c "import pysail" 2>/dev/null; then
              pip install --quiet --upgrade pip
              pip install --quiet pysail "pyspark[connect]" pytest ptpython
            fi

            export SPARK_BACKEND=pysail
            export PS1="⛵ \[\e[36m\]\W\[\e[0m\] $ "
            export PTPYTHON_CONFIG_HOME="$PWD/.ptpython"

            # fzf history search (Ctrl+R)
            eval "$(fzf --bash)"

            # Aliases
            alias t="pytest -v"
            alias ts="SPARK_BACKEND=pysail pytest -v"
            alias r="ruff check ."
            alias rf="ruff check --fix . && ruff format ."
          '';
        };
      }
    );
}
