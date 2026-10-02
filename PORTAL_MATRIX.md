# Portal Readiness Matrix

| Portal | Discovery/Search | Login framework | Result extraction | Real-account validation | Form inspect | Fill | Submit |
|---|---|---|---|---|---|---|---|
| Greenhouse | QA ready | Usually not required | QA ready | N/A | Planned | Planned | Disabled |
| Lever | QA ready | Usually not required | QA ready | N/A | Planned | Planned | Disabled |
| LinkedIn | Browser search navigation implemented | Browser adapter implemented | Implemented, selector-based, fail-closed | No | Generic inspector ready | Not yet implemented | Disabled |
| Naukri | Browser search navigation implemented | Browser adapter implemented | Implemented, selector-based, fail-closed | No | Generic inspector ready | Not yet implemented | Disabled |
| Indeed | Adapter registered | Framework only | Not yet implemented | No | Framework only | Not yet implemented | Disabled |
| Wellfound | Adapter registered | Framework only | Not yet implemented | No | Framework only | Not yet implemented | Disabled |
| Glassdoor | Adapter registered | Framework only | Not yet implemented | No | Framework only | Not yet implemented | Disabled |
| Instahyre | Adapter registered | Framework only | Not yet implemented | No | Framework only | Not yet implemented | Disabled |
| Cutshort | Adapter registered | Framework only | Not yet implemented | No | Framework only | Not yet implemented | Disabled |
| Foundit | Adapter registered | Framework only | Not yet implemented | No | Framework only | Not yet implemented | Disabled |
| Hirist | Adapter registered | Framework only | Not yet implemented | No | Framework only | Not yet implemented | Disabled |

Selectors are isolated inside portal adapters because portal DOMs change. Empty/ambiguous extraction returns no jobs instead of inventing data. Real-account validation is a separate gate and requires a user-owned browser session.
