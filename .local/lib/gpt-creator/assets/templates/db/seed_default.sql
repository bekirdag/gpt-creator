-- Default idempotent seeds (safe to run multiple times)
SET NAMES utf8mb4;

-- class_types
CREATE TABLE IF NOT EXISTS class_types (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  `key` VARCHAR(40) UNIQUE NOT NULL,
  label_tr VARCHAR(80) NOT NULL,
  label_en VARCHAR(80) NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO class_types (`key`, label_tr, label_en) VALUES
  ('seviye-1','Seviye 1','Level 1'),
  ('seviye-2','Seviye 2','Level 2'),
  ('her-seviye','Tüm Seviyeler','All Levels'),
  ('aerial-flow','Hava Akışı','Aerial Flow'),
  ('hamile-program','Hamile Programı','Prenatal')
ON DUPLICATE KEY UPDATE label_tr=VALUES(label_tr), label_en=VALUES(label_en);

-- instructors
CREATE TABLE IF NOT EXISTS instructors (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  slug VARCHAR(80) UNIQUE NOT NULL,
  full_name VARCHAR(120) NOT NULL,
  photo_url TEXT NULL,
  short_bio TEXT NULL,
  specialties TEXT NULL,
  display_order INT DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO instructors (slug, full_name, short_bio, display_order) VALUES
  ('burcu','Burcu', 'Eğitmen', 1),
  ('ceren','Ceren', 'Eğitmen', 2),
  ('fulya','Fulya', 'Eğitmen', 3),
  ('nilay','Nilay', 'Eğitmen', 4)
ON DUPLICATE KEY UPDATE full_name=VALUES(full_name);

-- pages (minimal placeholders)
CREATE TABLE IF NOT EXISTS pages (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  slug VARCHAR(120) UNIQUE NOT NULL,
  title VARCHAR(160) NOT NULL,
  body TEXT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO pages (slug, title, body) VALUES
  ('gizlilik','Gizlilik','Gizlilik Politikası (taslak)'),
  ('kvkk','KVKK','KVKK Aydınlatma Metni (taslak)'),
  ('sartlar','Şartlar','Kullanım Şartları (taslak)')
ON DUPLICATE KEY UPDATE title=VALUES(title);

