"""Hard guard: launch product Reels may use only real Empty Chair app screenshots.

Marketing/mascot art such as setup.png is intentionally excluded.
"""
import v2_instagram_reels_launch as launch

# These files are captures of real Empty Chair application screens.
REAL_APP_SCREENS = {
    "artists.png",
    "calendar.png",
    "settings.png",
    "openings-recovery.png",
    "operations.png",
    "revenue.png",
    "customers.png",
    "customer-intelligence.png",
}

# Replace the two launch sequences that previously included setup.png artwork.
launch.PRODUCT_LIBRARY[0]["assets"] = [
    "artists.png",
    "calendar.png",
    "settings.png",
    "openings-recovery.png",
    "operations.png",
]
launch.PRODUCT_LIBRARY[9]["assets"] = [
    "artists.png",
    "calendar.png",
    "openings-recovery.png",
    "revenue.png",
    "operations.png",
]

# Fail closed if marketing artwork ever gets added to these Reel definitions again.
for item in launch.PRODUCT_LIBRARY:
    bad = [asset for asset in item["assets"] if asset not in REAL_APP_SCREENS]
    if bad:
        raise RuntimeError(f"Non-app Reel assets blocked for {item['key']}: {bad}")
