"""Where the logo lives and what colour the business is.

One place, so a new logo or a change of shade is a single edit rather than a
hunt through the pages, the theme file and the PDF renderer.
"""

from __future__ import annotations

from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "assets"

#: The full lockup - mark, name and tagline - on a transparent background.
LOGO = ASSETS / "logo.png"
#: The mark on its own, for the browser tab and the collapsed sidebar.
ICON = ASSETS / "icon.png"
#: A smaller copy for the quote PDF - that file gets emailed to guests, so it
#: is sized for printing rather than for a screen.
LOGO_PRINT = ASSETS / "logo-print.png"

# Taken from the artwork itself rather than eyeballed.
NAVY = "#072647"
BLUE = "#0064d6"

BUSINESS_NAME = "RentalMan"
TAGLINE = "Flat rental management made simple"
