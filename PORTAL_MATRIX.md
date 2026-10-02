# Portal Readiness Matrix

| Portal | Search foundation | Full JD enrichment | Real-account validation | Form inspect/fill | Submit |
|---|---|---|---|---|---|
| Greenhouse | QA ready | Supported | N/A | Planned | Disabled |
| Lever | QA ready | Supported | N/A | Planned | Disabled |
| LinkedIn | Implemented | Supported | Pending | Generic inspector only | Disabled |
| Naukri | Implemented | Supported | Pending | Generic inspector only | Disabled |
| Indeed | Search URL implemented | Supported | Pending | Planned | Disabled |
| Foundit | Start-route registered | Supported | Pending | Planned | Disabled |
| Instahyre | Authenticated opportunities route registered | Supported | Pending | Planned | Disabled |
| Cutshort | Search URL implemented | Supported | Pending | Planned | Disabled |
| Wellfound | Jobs route registered | Supported | Pending | Planned | Disabled |
| Hirist | Start-route registered | Supported | Pending | Planned | Disabled |
| Glassdoor | Start-route registered | Supported | Pending | Planned | Disabled |
| Workday | Company-specific adapter target | Supported | N/A/company-specific | Planned | Disabled |

All sources feed one normalized Job model and one cross-portal duplicate guard. Portal selectors are intentionally isolated and must be validated against a real user-owned session before a portal is marked ready.
