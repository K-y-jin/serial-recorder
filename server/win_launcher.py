"""PyInstaller entry point for the Windows build of the server app.

Run directly (`python -m server.win_launcher`) or via the frozen exe
produced by `pyinstaller server.spec`. Just forwards to server.app.main.
"""
from server.app import main

if __name__ == "__main__":
    main()
