{
  description = "⛵ dev-nix-sail - Nix-configured development environment for Sail/PySpark";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };
        python = pkgs.python312;
      in {
        devShells.default = pkgs.mkShell {
          name = "dev-nix-sail";

          buildInputs = [
            python
            pkgs.jdk17
            pkgs.fzf
          ] ++ pkgs.lib.optionals pkgs.stdenv.isLinux [
            pkgs.stdenv.cc.cc.lib
            pkgs.zlib
          ];

          shellHook = ''
            ${pkgs.lib.optionalString pkgs.stdenv.isLinux ''
              export LD_LIBRARY_PATH="${pkgs.stdenv.cc.cc.lib}/lib:${pkgs.zlib}/lib:$LD_LIBRARY_PATH"
            ''}
            echo "⛵ dev-nix-sail - Development environment"
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
            echo "Aliases: t (test), ts (pysail), tp (pyspark), r (ruff), rf (ruff fix)"
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
          name = "dev-nix-sail-pysail";

          buildInputs = [
            python
            pkgs.fzf
          ] ++ pkgs.lib.optionals pkgs.stdenv.isLinux [
            pkgs.stdenv.cc.cc.lib
            pkgs.zlib
          ];

          shellHook = ''
            ${pkgs.lib.optionalString pkgs.stdenv.isLinux ''
              export LD_LIBRARY_PATH="${pkgs.stdenv.cc.cc.lib}/lib:${pkgs.zlib}/lib:$LD_LIBRARY_PATH"
            ''}
            echo "⛵ dev-nix-sail - PySail only (no Java)"
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
