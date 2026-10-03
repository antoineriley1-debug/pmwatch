#!/bin/bash
# TWINEY demo: synthetic feed, no IBKR needed.
cd "$(dirname "$0")"
exec ./start_twiney.command --demo
