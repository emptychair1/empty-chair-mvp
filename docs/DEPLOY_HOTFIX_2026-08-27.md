# Deploy hotfix — 2026-08-27

Temporarily remove `demand_pilot_bootstrap` from the production startup import path after the Render deploy failed immediately after PR #130.

The demand launch console remains loaded through `demand_acquisition`. The pilot bootstrap module remains in the repository for follow-up diagnosis and can be re-registered after the exact Render error is confirmed.
