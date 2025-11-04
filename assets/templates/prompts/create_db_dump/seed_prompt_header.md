You are preparing production-quality seed data for a freshly provisioned MySQL database.

Instructions:
- Use the provided schema to craft INSERT statements that populate reference data, configuration defaults, sample content, feature flags, roles/permissions, enumerations, and critical bootstrap records required for the system to operate end-to-end.
- Provide realistic values, respecting all constraints, foreign keys, and unique indexes.
- Cover every table that must start non-empty (including lookup tables and essential user accounts).
- Avoid dummy lorem ipsum; align the seed data with the domain terminology found in the SDS.
- Wrap the output as executable SQL: include `START TRANSACTION;` and `COMMIT;` around the inserts, and set `SET NAMES utf8mb4;` at the start.
- Output SQL only—no prose or code fences.

## Database Schema
