"""python -m flcmd (also the pythonw.exe target for Windows shortcuts)."""

import sys

from flcmd.app import main

if __name__ == "__main__":
    sys.exit(main())
