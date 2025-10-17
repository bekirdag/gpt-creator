-- init.sql.tmpl — MySQL initialization
-- Placeholders: test_db, gc_test_user, kmYqMonc4uY7Q2RQUB1sSvMk6WjDroDH

CREATE DATABASE IF NOT EXISTS `test_db` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- Create application user if not exists
CREATE USER IF NOT EXISTS 'gc_test_user'@'%' IDENTIFIED BY 'kmYqMonc4uY7Q2RQUB1sSvMk6WjDroDH';

-- Grant privileges on the app database
GRANT ALL PRIVILEGES ON `test_db`.* TO 'gc_test_user'@'%';

-- Recommended SQL modes
SET GLOBAL sql_mode = 'STRICT_TRANS_TABLES,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION';

FLUSH PRIVILEGES;
