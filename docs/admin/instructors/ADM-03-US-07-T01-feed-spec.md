# ADM-03-US-07-T01 Feed Specification

## Overview
- **Purpose:** Describe the data feed that powers the ADM-03 Instructor assignment experience.
- **Consumers:** Admin portal workflow (US-07) and downstream reporting jobs.
- **Owners:** Platform Data Engineering (primary), Instructor Experience Squad (secondary).

## Source Systems
| System | Endpoint / Table | Contact | Notes |
| --- | --- | --- | --- |
| CRM | `crm.instructors` view | data-eng@company.com | Authoritative instructor roster |
| Scheduling | `scheduler.assignments` export | scheduling-team@company.com | Provides availability windows |
| Compliance | `compliance.certifications` API | compliance@company.com | License & certification status |

## Delivery Contract
- **Format:** UTF-8 CSV, comma delimited, header row required.
- **Transport:** Uploaded to S3 bucket `s3://adm-prod/instructors/feeds/` with server-side encryption (SSE-S3).
- **File Naming:** `instructor_feed_<YYYYMMDD_HHMMSS>.csv` using UTC timestamp.
- **Schedule:** Hourly, :10 past the hour. Late threshold is 5 minutes.
- **Retention:** Minimum 30 days in S3, then archived to Glacier.

## Data Elements
| Column | Type | Source | Description |
| --- | --- | --- | --- |
| `instructor_id` | string | CRM | Stable unique identifier |
| `full_name` | string | CRM | Preferred display name |
| `email` | string | CRM | Used for notifications |
| `phone` | string | CRM | Optional; E.164 formatted |
| `status` | enum (`active`,`inactive`,`pending`) | CRM | Controls visibility |
| `primary_discipline` | string | CRM | Used for filtering |
| `availability_start` | datetime (UTC) | Scheduling | First slot available |
| `availability_end` | datetime (UTC) | Scheduling | Last slot available |
| `certification_level` | string | Compliance | Highest valid certification |
| `certification_expiration` | date | Compliance | Must be >= run date |

## Validation Rules
- Reject file if any required column is missing from header.
- Reject row if `instructor_id` is blank or duplicated.
- Reject row if `status` not in allowed enum.
- Soft warn when certification expiration is < 30 days from run timestamp.

## Error Handling & Notifications
- Delivery failure publishes message to `adm.ops.feed-failures` topic with error payload.
- Data validation failures produce detailed report in `s3://adm-prod/instructors/validation/`.
- PagerDuty escalation: "Instructor Feed Outage" (auto-trigger after 2 consecutive failures).

## Security & Compliance
- Access limited to IAM role `adm-instructor-feed-writer`.
- All files encrypted at rest and in transit (TLS 1.2+).
- PII review completed; feed classified as "Restricted".

## Testing & Rollout
1. Dry run in staging bucket `s3://adm-stg/instructors/feeds/`.
2. Validate with 3 historical backfills and compare to portal renders.
3. Enable hourly schedule after sign-off from Instructor Experience product owner.

## Open Questions
- Confirm whether phone number should be present for inactive instructors.
- Clarify retention policy once data lake ingestion is live.
