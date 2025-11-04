You are a principal database architect. Design a MySQL schema that fully supports the system described in the SDS.

Instructions:
- Produce a complete SQL dump suitable for `mysql < schema.sql`.
- Define databases, tables, columns with data types, defaults, nullability, character sets, indexes, primary keys, foreign keys, unique constraints, and check constraints where appropriate.
- Model relationships explicitly with foreign keys, cascading rules, and junction tables.
- Include derived tables needed for analytics, audit, compliance, or background processing called out in the SDS.
- Add necessary views or stored routines only if they are critical to system operation.
- Use consistent naming conventions and comment statements (`-- ...`) to explain non-obvious design decisions.
- Ensure the schema is normalized but pragmatic—denormalize when the SDS calls for performance considerations.
- Output only SQL (no code fences, no prose outside of SQL comments).

## SDS Excerpt
