# Retired ScanSafe application

`legacy-scansafe/` preserves the old QR-checker product as reference material. These files are not active routes, pages, background workers or default tests.

Moved here: the old web interface (including map, dashboard and onboarding), financial/account/payment APIs, Dogwood and ParkMobile demos, old Chert payment agent, Tiger/Typesense data layer, demo assets, evaluations, deployment scripts, handoffs, team checklist and the old test suite. Existing sandbox browsing/network guards and QR scoring remain active infrastructure. Some operator helpers remain internal dependencies of the browser worker; `/operate/stream` is no longer registered.

Old documentation describes historical deployments and can be stale. Do not run archived deployment or financial scripts as part of the factory setup. Archive imports have not been rewritten to run from this directory.

To restore the exact old product in a separate checkout, use the parent commit of the factory pivot (the GitHub parent is `c259051078dec78bbb6cb063266905ae3e8fe17d`). No server resources, databases, accounts or deployments were deleted by archiving these files.
