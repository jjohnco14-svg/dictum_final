#!/usr/bin/env python3
import sys
import os

# Add the dictumc package to path
base = os.path.join(os.path.dirname(__file__), 'dictum-development', 'scripts', 'dictum_compiler', 'compiler')
sys.path.insert(0, base)

from dictumc_cli import main
sys.exit(main())
