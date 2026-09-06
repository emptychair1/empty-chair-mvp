"""Instagram growth milestone policy.

$1K MRR is milestone one, never a shutdown condition. Also pins the public Empty Chair
Instagram professional account id so only secrets need runtime configuration.
"""
import v2_instagram_growth as growth

EMPTY_CHAIR_IG_USER_ID = "17841430067241664"

growth.IG_USER_ID = growth.IG_USER_ID or EMPTY_CHAIR_IG_USER_ID
growth.growth_live = lambda: True
