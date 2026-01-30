"""ptpython configuration for test-sail project."""


def configure(repl):
    """Configure ptpython REPL."""
    # Fuzzy completion (like fzf)
    repl.enable_fuzzy_completion = True

    # History search with Ctrl+R
    repl.enable_history_search = True

    # Syntax highlighting
    repl.highlight_matching_parenthesis = True

    # Show function signature
    repl.enable_auto_suggest = True

    # Complete while typing
    repl.complete_while_typing = True

    # Show docstrings in completion popup
    repl.enable_input_validation = True

    # Mouse support
    repl.enable_mouse_support = False

    # Vi mode (False = Emacs-style keybindings)
    repl.vi_mode = False

    # Paste mode (auto-detect multi-line paste)
    repl.paste_mode = False

    # Prompt style
    repl.prompt_style = "classic"  # 'classic', 'ipython'

    # Show status bar
    repl.show_status_bar = True

    # Color scheme
    repl.use_code_colorscheme("monokai")
