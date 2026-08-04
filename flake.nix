{
  description = "⛵ dev-nix-sail - Nix-configured development environment for Sail/PySpark";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
    devshell.url = "github:numtide/devshell";
    devshell.inputs.nixpkgs.follows = "nixpkgs";
  };

  outputs = { self, nixpkgs, flake-utils, devshell }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs {
          inherit system;
          overlays = [ devshell.overlays.default ];
        };
        inherit (pkgs) lib stdenv;

        python = pkgs.python312;

        # Native libraries the PySail wheel needs at runtime on Linux.
        linuxLibs = lib.optionals stdenv.isLinux [ stdenv.cc.cc.lib pkgs.zlib ];

        linuxEnv = lib.optionals stdenv.isLinux [
          {
            name = "LD_LIBRARY_PATH";
            prefix = "${stdenv.cc.cc.lib}/lib:${pkgs.zlib}/lib";
          }
        ];

        commonEnv = [
          # Default, not an override: CI (and `SPARK_BACKEND=pyspark nix develop`)
          # must be able to pick the backend from outside the shell.
          { name = "SPARK_BACKEND"; eval = "\${SPARK_BACKEND:-pysail}"; }
          { name = "PTPYTHON_CONFIG_HOME"; eval = "$PRJ_ROOT/.ptpython"; }
        ] ++ linuxEnv;

        # A venv is only up to date for a given (pyproject.toml, extras) pair, so
        # stamp it with a hash of both. Checking "is pysail importable" instead
        # would leave the venv frozen at whatever it was installed with, and
        # dependency bumps would never reach it.
        venvStamp = extras: ''
          venv_stamp_want() {
            echo "$(${pkgs.coreutils}/bin/sha256sum "$PRJ_ROOT/pyproject.toml" | ${pkgs.coreutils}/bin/cut -d' ' -f1) ${extras}"
          }
          venv_stamp_file="$PRJ_ROOT/.venv-nix/.pyproject-stamp"
        '';

        # The venv must be created and activated in the shell itself, not in a
        # command: commands run in a subshell and cannot change our environment.
        venvStartup = { extras, animate }: ''
          ${venvStamp extras}

          # -x also catches a venv whose interpreter was garbage collected by Nix.
          if [ ! -x "$PRJ_ROOT/.venv-nix/bin/python" ]; then
            if [ -d "$PRJ_ROOT/.venv-nix" ]; then
              echo "Recreating stale virtual environment..."
              rm -rf "$PRJ_ROOT/.venv-nix"
            else
              echo "Creating virtual environment..."
            fi
            ${python}/bin/python -m venv "$PRJ_ROOT/.venv-nix"
          fi

          source "$PRJ_ROOT/.venv-nix/bin/activate"

          if [ "$(cat "$venv_stamp_file" 2>/dev/null)" != "$(venv_stamp_want)" ]; then
            echo "Syncing dependencies from pyproject.toml..."
            pip install --quiet --upgrade pip
            ${if animate then ''
              pip install --quiet -e "$PRJ_ROOT[dev]" ${extras} &
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

              wait $PIP_PID && PIP_RC=0 || PIP_RC=$?
            '' else ''
              pip install --quiet -e "$PRJ_ROOT[dev]" ${extras} && PIP_RC=0 || PIP_RC=$?
            ''}

            # Only stamp the venv if pip actually succeeded, so a failed sync is
            # retried on the next shell entry instead of being cached as good.
            if [ "$PIP_RC" -eq 0 ]; then
              venv_stamp_want > "$venv_stamp_file"
            else
              echo "Dependency sync failed (pip exit $PIP_RC) - the venv is out of sync." >&2
            fi
          fi
        '';

        # Ctrl+R history search, interactive shells only.
        fzfStartup = ''
          eval "$(fzf --bash)"
          export PS1="⛵ \[\e[36m\]\W\[\e[0m\] $ "
        '';

        testCommands = [
          {
            category = "test";
            name = "t";
            help = "Run the test suite with the default backend";
            command = ''pytest -v "$@"'';
          }
          {
            category = "test";
            name = "ts";
            help = "Run the test suite against PySail (no Java)";
            command = ''SPARK_BACKEND=pysail pytest -v "$@"'';
          }
        ];

        lintCommands = [
          {
            category = "lint";
            name = "r";
            help = "Check the code with ruff";
            command = ''ruff check "''${@:-.}"'';
          }
          {
            category = "lint";
            name = "rf";
            help = "Fix and format the code with ruff";
            command = ''ruff check --fix "''${@:-.}" && ruff format "''${@:-.}"'';
          }
        ];

        envCommands = extras: [
          {
            category = "env";
            name = "venv-sync";
            help = "Reinstall the Python dependencies from pyproject.toml";
            command = ''
              ${venvStamp extras}
              pip install --quiet --upgrade pip
              pip install -e "$PRJ_ROOT[dev]" ${extras} "$@" || exit $?
              venv_stamp_want > "$venv_stamp_file"
            '';
          }
          {
            category = "env";
            name = "venv-reset";
            help = "Delete .venv-nix (re-enter the shell to rebuild it)";
            command = ''rm -rf "$PRJ_ROOT/.venv-nix"'';
          }
        ];
      in {
        devShells.default = pkgs.devshell.mkShell {
          name = "dev-nix-sail";

          motd = ''
            {202}⛵ dev-nix-sail{reset} - Development environment
            $(type -p menu &>/dev/null && menu)
          '';

          packages = [ python pkgs.jdk17 pkgs.fzf ] ++ linuxLibs;

          # An override, not a default: PySpark reads JAVA_HOME before PATH, so a
          # JAVA_HOME inherited from the outside shell (SDKMAN, for instance)
          # decides which JVM runs and the jdk17 of this shell never gets used.
          env = commonEnv ++ [
            { name = "JAVA_HOME"; value = pkgs.jdk17.home; }
          ];

          commands = testCommands ++ [
            {
              category = "test";
              name = "tp";
              help = "Run the test suite against PySpark (needs Java)";
              command = ''SPARK_BACKEND=pyspark pytest -v "$@"'';
            }
          ] ++ lintCommands ++ envCommands "ptpython colorlog";

          devshell.startup.venv.text = venvStartup {
            extras = "ptpython colorlog";
            animate = true;
          };

          devshell.interactive.fzf.text = fzfStartup;
        };

        devShells.pysail = pkgs.devshell.mkShell {
          name = "dev-nix-sail-pysail";

          motd = ''
            {202}⛵ dev-nix-sail{reset} - PySail only (no Java)
            $(type -p menu &>/dev/null && menu)
          '';

          packages = [ python pkgs.fzf ] ++ linuxLibs;

          env = commonEnv;

          commands = testCommands ++ lintCommands ++ envCommands "ptpython";

          devshell.startup.venv.text = venvStartup {
            extras = "ptpython";
            animate = false;
          };

          devshell.interactive.fzf.text = fzfStartup;
        };
      }
    );
}
