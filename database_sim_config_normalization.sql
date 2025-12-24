-- =============================================================================
-- Game Simulation Config Normalization
-- =============================================================================
-- This script creates a fully normalized schema for game simulation configuration,
-- replacing the single baseline_outcomes_json column with proper relational tables.
--
-- Run this script against your database to set up the new schema.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- PHASE 1: Static Reference Tables
-- -----------------------------------------------------------------------------

-- 1.1 Field Zones - Horizontal spray chart zones
CREATE TABLE IF NOT EXISTS field_zones (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(50) NOT NULL UNIQUE,
    display_name VARCHAR(50) NOT NULL,
    spread_angle INT NOT NULL DEFAULT 14,
    sort_order INT NOT NULL
);

INSERT INTO field_zones (name, display_name, spread_angle, sort_order) VALUES
    ('far_left', 'Far Left', 14, 1),
    ('left', 'Left', 14, 2),
    ('center_left', 'Center Left', 14, 3),
    ('dead_center', 'Dead Center', 14, 4),
    ('center_right', 'Center Right', 14, 5),
    ('right', 'Right', 14, 6),
    ('far_right', 'Far Right', 14, 7)
ON DUPLICATE KEY UPDATE display_name = VALUES(display_name);


-- 1.2 Distance Zones - Depth zones from home plate
CREATE TABLE IF NOT EXISTS distance_zones (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(50) NOT NULL UNIQUE,
    display_name VARCHAR(50) NOT NULL,
    sort_order INT NOT NULL
);

INSERT INTO distance_zones (name, display_name, sort_order) VALUES
    ('homerun', 'Home Run', 1),
    ('deep_of', 'Deep Outfield', 2),
    ('middle_of', 'Middle Outfield', 3),
    ('shallow_of', 'Shallow Outfield', 4),
    ('deep_if', 'Deep Infield', 5),
    ('middle_if', 'Middle Infield', 6),
    ('shallow_if', 'Shallow Infield', 7),
    ('mound', 'Mound', 8),
    ('catcher', 'Catcher', 9)
ON DUPLICATE KEY UPDATE display_name = VALUES(display_name);


-- 1.3 Contact Types - Quality of contact
CREATE TABLE IF NOT EXISTS contact_types (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(50) NOT NULL UNIQUE,
    display_name VARCHAR(50) NOT NULL,
    sort_order INT NOT NULL
);

INSERT INTO contact_types (name, display_name, sort_order) VALUES
    ('barrel', 'Barrel', 1),
    ('solid', 'Solid', 2),
    ('flare', 'Flare', 3),
    ('burner', 'Burner', 4),
    ('under', 'Under', 5),
    ('topped', 'Topped', 6),
    ('weak', 'Weak', 7)
ON DUPLICATE KEY UPDATE display_name = VALUES(display_name);


-- 1.4 Fielding Outcomes - Result of fielding attempt
CREATE TABLE IF NOT EXISTS fielding_outcomes (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(50) NOT NULL UNIQUE,
    display_name VARCHAR(50) NOT NULL,
    sort_order INT NOT NULL
);

INSERT INTO fielding_outcomes (name, display_name, sort_order) VALUES
    ('out', 'Out', 1),
    ('single', 'Single', 2),
    ('double', 'Double', 3),
    ('triple', 'Triple', 4)
ON DUPLICATE KEY UPDATE display_name = VALUES(display_name);


-- 1.5 Defensive Positions - Fielding positions
CREATE TABLE IF NOT EXISTS defensive_positions (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(50) NOT NULL UNIQUE,
    abbreviation VARCHAR(10) NOT NULL,
    is_infield BOOLEAN NOT NULL DEFAULT FALSE,
    is_outfield BOOLEAN NOT NULL DEFAULT FALSE,
    sort_order INT NOT NULL
);

INSERT INTO defensive_positions (name, abbreviation, is_infield, is_outfield, sort_order) VALUES
    ('pitcher', 'P', TRUE, FALSE, 1),
    ('catcher', 'C', TRUE, FALSE, 2),
    ('firstbase', '1B', TRUE, FALSE, 3),
    ('secondbase', '2B', TRUE, FALSE, 4),
    ('thirdbase', '3B', TRUE, FALSE, 5),
    ('shortstop', 'SS', TRUE, FALSE, 6),
    ('leftfield', 'LF', FALSE, TRUE, 7),
    ('centerfield', 'CF', FALSE, TRUE, 8),
    ('rightfield', 'RF', FALSE, TRUE, 9)
ON DUPLICATE KEY UPDATE abbreviation = VALUES(abbreviation);


-- 1.6 Fielding Difficulty Levels - Play difficulty categories
CREATE TABLE IF NOT EXISTS fielding_difficulty_levels (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(50) NOT NULL UNIQUE,
    display_name VARCHAR(100) NOT NULL,
    difficulty_modifier FLOAT NOT NULL DEFAULT 1.0,
    sort_order INT NOT NULL
);

INSERT INTO fielding_difficulty_levels (name, display_name, difficulty_modifier, sort_order) VALUES
    ('directlyat', 'Directly At', 1.0, 1),
    ('onestepaway', 'One Step Away', 0.9, 2),
    ('twostepaway', 'Two Steps Away', 0.75, 3),
    ('threestepaway', 'Three Steps Away', 0.5, 4),
    ('homerun', 'Home Run (Uncatchable)', 0.0, 5)
ON DUPLICATE KEY UPDATE display_name = VALUES(display_name);


-- -----------------------------------------------------------------------------
-- PHASE 2: Static Mapping Tables
-- -----------------------------------------------------------------------------

-- 2.1 Defensive Alignment - Which positions field which zone/distance
CREATE TABLE IF NOT EXISTS defensive_alignment (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    field_zone_id INT UNSIGNED NOT NULL,
    distance_zone_id INT UNSIGNED NOT NULL,
    position_id INT UNSIGNED NOT NULL,
    priority INT NOT NULL DEFAULT 1,

    UNIQUE KEY uk_alignment (field_zone_id, distance_zone_id, position_id),
    INDEX idx_zone_lookup (field_zone_id, distance_zone_id),

    FOREIGN KEY (field_zone_id) REFERENCES field_zones(id),
    FOREIGN KEY (distance_zone_id) REFERENCES distance_zones(id),
    FOREIGN KEY (position_id) REFERENCES defensive_positions(id)
);

-- Populate defensive alignment based on the original JSON data
-- Far Left zone alignments
INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 1
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'far_left' AND dz.name = 'deep_of' AND dp.name = 'leftfield'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 1
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'far_left' AND dz.name = 'middle_of' AND dp.name = 'leftfield'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 1
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'far_left' AND dz.name = 'shallow_of' AND dp.name = 'leftfield'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 1
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'far_left' AND dz.name = 'deep_if' AND dp.name = 'thirdbase'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 1
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'far_left' AND dz.name = 'middle_if' AND dp.name = 'thirdbase'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 1
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'far_left' AND dz.name = 'shallow_if' AND dp.name = 'thirdbase'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 1
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'far_left' AND dz.name = 'mound' AND dp.name = 'thirdbase'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 2
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'far_left' AND dz.name = 'mound' AND dp.name = 'pitcher'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 1
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'far_left' AND dz.name = 'catcher' AND dp.name = 'catcher'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

-- Left zone alignments
INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 1
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'left' AND dz.name = 'deep_of' AND dp.name = 'leftfield'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 1
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'left' AND dz.name = 'middle_of' AND dp.name = 'leftfield'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 1
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'left' AND dz.name = 'shallow_of' AND dp.name = 'leftfield'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 1
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'left' AND dz.name = 'deep_if' AND dp.name = 'shortstop'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 1
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'left' AND dz.name = 'middle_if' AND dp.name = 'shortstop'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 1
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'left' AND dz.name = 'shallow_if' AND dp.name = 'shortstop'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 2
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'left' AND dz.name = 'shallow_if' AND dp.name = 'thirdbase'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 1
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'left' AND dz.name = 'mound' AND dp.name = 'thirdbase'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 2
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'left' AND dz.name = 'mound' AND dp.name = 'shortstop'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 3
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'left' AND dz.name = 'mound' AND dp.name = 'pitcher'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 1
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'left' AND dz.name = 'catcher' AND dp.name = 'catcher'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

-- Center Left zone alignments
INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 1
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'center_left' AND dz.name = 'deep_of' AND dp.name = 'centerfield'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 2
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'center_left' AND dz.name = 'deep_of' AND dp.name = 'leftfield'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 1
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'center_left' AND dz.name = 'middle_of' AND dp.name = 'centerfield'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 2
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'center_left' AND dz.name = 'middle_of' AND dp.name = 'leftfield'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 1
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'center_left' AND dz.name = 'shallow_of' AND dp.name = 'centerfield'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 2
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'center_left' AND dz.name = 'shallow_of' AND dp.name = 'leftfield'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 1
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'center_left' AND dz.name = 'deep_if' AND dp.name = 'shortstop'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 1
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'center_left' AND dz.name = 'middle_if' AND dp.name = 'shortstop'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 1
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'center_left' AND dz.name = 'shallow_if' AND dp.name = 'shortstop'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 1
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'center_left' AND dz.name = 'mound' AND dp.name = 'shortstop'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 2
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'center_left' AND dz.name = 'mound' AND dp.name = 'pitcher'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 1
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'center_left' AND dz.name = 'catcher' AND dp.name = 'catcher'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

-- Dead Center zone alignments
INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 1
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'dead_center' AND dz.name = 'deep_of' AND dp.name = 'centerfield'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 1
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'dead_center' AND dz.name = 'middle_of' AND dp.name = 'centerfield'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 1
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'dead_center' AND dz.name = 'shallow_of' AND dp.name = 'centerfield'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 1
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'dead_center' AND dz.name = 'deep_if' AND dp.name = 'shortstop'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 2
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'dead_center' AND dz.name = 'deep_if' AND dp.name = 'secondbase'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 1
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'dead_center' AND dz.name = 'middle_if' AND dp.name = 'shortstop'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 2
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'dead_center' AND dz.name = 'middle_if' AND dp.name = 'secondbase'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 1
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'dead_center' AND dz.name = 'shallow_if' AND dp.name = 'shortstop'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 2
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'dead_center' AND dz.name = 'shallow_if' AND dp.name = 'secondbase'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 1
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'dead_center' AND dz.name = 'mound' AND dp.name = 'pitcher'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 1
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'dead_center' AND dz.name = 'catcher' AND dp.name = 'catcher'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

-- Center Right zone alignments
INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 1
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'center_right' AND dz.name = 'deep_of' AND dp.name = 'centerfield'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 2
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'center_right' AND dz.name = 'deep_of' AND dp.name = 'rightfield'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 1
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'center_right' AND dz.name = 'middle_of' AND dp.name = 'centerfield'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 2
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'center_right' AND dz.name = 'middle_of' AND dp.name = 'rightfield'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 1
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'center_right' AND dz.name = 'shallow_of' AND dp.name = 'centerfield'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 2
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'center_right' AND dz.name = 'shallow_of' AND dp.name = 'rightfield'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 1
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'center_right' AND dz.name = 'deep_if' AND dp.name = 'secondbase'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 1
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'center_right' AND dz.name = 'middle_if' AND dp.name = 'secondbase'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 1
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'center_right' AND dz.name = 'shallow_if' AND dp.name = 'secondbase'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 1
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'center_right' AND dz.name = 'mound' AND dp.name = 'secondbase'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 2
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'center_right' AND dz.name = 'mound' AND dp.name = 'pitcher'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 1
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'center_right' AND dz.name = 'catcher' AND dp.name = 'catcher'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

-- Right zone alignments
INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 1
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'right' AND dz.name = 'deep_of' AND dp.name = 'rightfield'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 1
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'right' AND dz.name = 'middle_of' AND dp.name = 'rightfield'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 1
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'right' AND dz.name = 'shallow_of' AND dp.name = 'rightfield'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 1
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'right' AND dz.name = 'deep_if' AND dp.name = 'secondbase'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 1
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'right' AND dz.name = 'middle_if' AND dp.name = 'secondbase'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 1
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'right' AND dz.name = 'shallow_if' AND dp.name = 'secondbase'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 2
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'right' AND dz.name = 'shallow_if' AND dp.name = 'firstbase'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 1
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'right' AND dz.name = 'mound' AND dp.name = 'firstbase'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 2
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'right' AND dz.name = 'mound' AND dp.name = 'secondbase'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 3
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'right' AND dz.name = 'mound' AND dp.name = 'pitcher'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 1
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'right' AND dz.name = 'catcher' AND dp.name = 'catcher'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

-- Far Right zone alignments
INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 1
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'far_right' AND dz.name = 'deep_of' AND dp.name = 'rightfield'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 1
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'far_right' AND dz.name = 'middle_of' AND dp.name = 'rightfield'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 1
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'far_right' AND dz.name = 'shallow_of' AND dp.name = 'rightfield'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 1
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'far_right' AND dz.name = 'deep_if' AND dp.name = 'firstbase'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 1
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'far_right' AND dz.name = 'middle_if' AND dp.name = 'firstbase'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 1
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'far_right' AND dz.name = 'shallow_if' AND dp.name = 'firstbase'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 1
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'far_right' AND dz.name = 'mound' AND dp.name = 'firstbase'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 2
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'far_right' AND dz.name = 'mound' AND dp.name = 'pitcher'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);

INSERT INTO defensive_alignment (field_zone_id, distance_zone_id, position_id, priority)
SELECT fz.id, dz.id, dp.id, 1
FROM field_zones fz, distance_zones dz, defensive_positions dp
WHERE fz.name = 'far_right' AND dz.name = 'catcher' AND dp.name = 'catcher'
ON DUPLICATE KEY UPDATE priority = VALUES(priority);


-- 2.2 Fielding Difficulty Mapping - Zone/distance to difficulty
CREATE TABLE IF NOT EXISTS fielding_difficulty_mapping (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    field_zone_id INT UNSIGNED NOT NULL,
    distance_zone_id INT UNSIGNED NOT NULL,
    difficulty_level_id INT UNSIGNED NOT NULL,

    UNIQUE KEY uk_difficulty (field_zone_id, distance_zone_id),

    FOREIGN KEY (field_zone_id) REFERENCES field_zones(id),
    FOREIGN KEY (distance_zone_id) REFERENCES distance_zones(id),
    FOREIGN KEY (difficulty_level_id) REFERENCES fielding_difficulty_levels(id)
);

-- Populate fielding difficulty based on original JSON
-- directlyat plays
INSERT INTO fielding_difficulty_mapping (field_zone_id, distance_zone_id, difficulty_level_id)
SELECT fz.id, dz.id, dl.id
FROM field_zones fz, distance_zones dz, fielding_difficulty_levels dl
WHERE dl.name = 'directlyat' AND (
    (fz.name = 'left' AND dz.name = 'middle_of') OR
    (fz.name = 'dead_center' AND dz.name = 'middle_of') OR
    (fz.name = 'right' AND dz.name = 'middle_of') OR
    (fz.name = 'far_left' AND dz.name = 'middle_if') OR
    (fz.name = 'center_left' AND dz.name = 'middle_if') OR
    (fz.name = 'center_right' AND dz.name = 'middle_if') OR
    (fz.name = 'far_right' AND dz.name = 'middle_if') OR
    (fz.name = 'dead_center' AND dz.name = 'mound') OR
    (dz.name = 'catcher')
)
ON DUPLICATE KEY UPDATE difficulty_level_id = VALUES(difficulty_level_id);

-- onestepaway plays
INSERT INTO fielding_difficulty_mapping (field_zone_id, distance_zone_id, difficulty_level_id)
SELECT fz.id, dz.id, dl.id
FROM field_zones fz, distance_zones dz, fielding_difficulty_levels dl
WHERE dl.name = 'onestepaway' AND (
    (fz.name = 'far_left' AND dz.name = 'deep_if') OR
    (fz.name = 'center_left' AND dz.name = 'deep_if') OR
    (fz.name = 'center_right' AND dz.name = 'deep_if') OR
    (fz.name = 'far_right' AND dz.name = 'deep_if') OR
    (fz.name = 'left' AND dz.name = 'middle_if') OR
    (fz.name = 'dead_center' AND dz.name = 'middle_if') OR
    (fz.name = 'right' AND dz.name = 'middle_if') OR
    (dz.name = 'shallow_if') OR
    (fz.name = 'left' AND dz.name = 'mound') OR
    (fz.name = 'center_left' AND dz.name = 'mound') OR
    (fz.name = 'center_right' AND dz.name = 'mound') OR
    (fz.name = 'right' AND dz.name = 'mound') OR
    (fz.name = 'far_right' AND dz.name = 'mound')
)
ON DUPLICATE KEY UPDATE difficulty_level_id = VALUES(difficulty_level_id);

-- twostepaway plays
INSERT INTO fielding_difficulty_mapping (field_zone_id, distance_zone_id, difficulty_level_id)
SELECT fz.id, dz.id, dl.id
FROM field_zones fz, distance_zones dz, fielding_difficulty_levels dl
WHERE dl.name = 'twostepaway' AND (
    (fz.name = 'left' AND dz.name = 'deep_of') OR
    (fz.name = 'dead_center' AND dz.name = 'deep_of') OR
    (fz.name = 'right' AND dz.name = 'deep_of') OR
    (fz.name = 'far_left' AND dz.name = 'middle_of') OR
    (fz.name = 'center_left' AND dz.name = 'middle_of') OR
    (fz.name = 'center_right' AND dz.name = 'middle_of') OR
    (fz.name = 'far_right' AND dz.name = 'middle_of') OR
    (fz.name = 'left' AND dz.name = 'shallow_of') OR
    (fz.name = 'dead_center' AND dz.name = 'shallow_of') OR
    (fz.name = 'right' AND dz.name = 'shallow_of') OR
    (fz.name = 'left' AND dz.name = 'deep_if') OR
    (fz.name = 'dead_center' AND dz.name = 'deep_if') OR
    (fz.name = 'right' AND dz.name = 'deep_if')
)
ON DUPLICATE KEY UPDATE difficulty_level_id = VALUES(difficulty_level_id);

-- threestepaway plays
INSERT INTO fielding_difficulty_mapping (field_zone_id, distance_zone_id, difficulty_level_id)
SELECT fz.id, dz.id, dl.id
FROM field_zones fz, distance_zones dz, fielding_difficulty_levels dl
WHERE dl.name = 'threestepaway' AND (
    (fz.name = 'far_left' AND dz.name = 'deep_of') OR
    (fz.name = 'center_left' AND dz.name = 'deep_of') OR
    (fz.name = 'center_right' AND dz.name = 'deep_of') OR
    (fz.name = 'far_right' AND dz.name = 'deep_of') OR
    (fz.name = 'far_left' AND dz.name = 'shallow_of') OR
    (fz.name = 'center_left' AND dz.name = 'shallow_of') OR
    (fz.name = 'center_right' AND dz.name = 'shallow_of') OR
    (fz.name = 'far_right' AND dz.name = 'shallow_of')
)
ON DUPLICATE KEY UPDATE difficulty_level_id = VALUES(difficulty_level_id);

-- homerun (uncatchable)
INSERT INTO fielding_difficulty_mapping (field_zone_id, distance_zone_id, difficulty_level_id)
SELECT fz.id, dz.id, dl.id
FROM field_zones fz, distance_zones dz, fielding_difficulty_levels dl
WHERE dl.name = 'homerun' AND dz.name = 'homerun'
ON DUPLICATE KEY UPDATE difficulty_level_id = VALUES(difficulty_level_id);


-- 2.3 Time to Ground - How long balls take to reach zones
CREATE TABLE IF NOT EXISTS time_to_ground (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    contact_type_id INT UNSIGNED NOT NULL,
    distance_zone_id INT UNSIGNED NOT NULL,
    time_value INT NOT NULL,

    UNIQUE KEY uk_time (contact_type_id, distance_zone_id),

    FOREIGN KEY (contact_type_id) REFERENCES contact_types(id),
    FOREIGN KEY (distance_zone_id) REFERENCES distance_zones(id)
);

-- Barrel time to ground
INSERT INTO time_to_ground (contact_type_id, distance_zone_id, time_value)
SELECT ct.id, dz.id, 2 FROM contact_types ct, distance_zones dz WHERE ct.name = 'barrel' AND dz.name = 'deep_of'
ON DUPLICATE KEY UPDATE time_value = VALUES(time_value);
INSERT INTO time_to_ground (contact_type_id, distance_zone_id, time_value)
SELECT ct.id, dz.id, 1 FROM contact_types ct, distance_zones dz WHERE ct.name = 'barrel' AND dz.name = 'middle_of'
ON DUPLICATE KEY UPDATE time_value = VALUES(time_value);
INSERT INTO time_to_ground (contact_type_id, distance_zone_id, time_value)
SELECT ct.id, dz.id, 1 FROM contact_types ct, distance_zones dz WHERE ct.name = 'barrel' AND dz.name = 'shallow_of'
ON DUPLICATE KEY UPDATE time_value = VALUES(time_value);

-- Solid time to ground
INSERT INTO time_to_ground (contact_type_id, distance_zone_id, time_value)
SELECT ct.id, dz.id, 3 FROM contact_types ct, distance_zones dz WHERE ct.name = 'solid' AND dz.name = 'deep_of'
ON DUPLICATE KEY UPDATE time_value = VALUES(time_value);
INSERT INTO time_to_ground (contact_type_id, distance_zone_id, time_value)
SELECT ct.id, dz.id, 2 FROM contact_types ct, distance_zones dz WHERE ct.name = 'solid' AND dz.name = 'middle_of'
ON DUPLICATE KEY UPDATE time_value = VALUES(time_value);
INSERT INTO time_to_ground (contact_type_id, distance_zone_id, time_value)
SELECT ct.id, dz.id, 1 FROM contact_types ct, distance_zones dz WHERE ct.name = 'solid' AND dz.name = 'shallow_of'
ON DUPLICATE KEY UPDATE time_value = VALUES(time_value);
INSERT INTO time_to_ground (contact_type_id, distance_zone_id, time_value)
SELECT ct.id, dz.id, 1 FROM contact_types ct, distance_zones dz WHERE ct.name = 'solid' AND dz.name = 'deep_if'
ON DUPLICATE KEY UPDATE time_value = VALUES(time_value);
INSERT INTO time_to_ground (contact_type_id, distance_zone_id, time_value)
SELECT ct.id, dz.id, 1 FROM contact_types ct, distance_zones dz WHERE ct.name = 'solid' AND dz.name = 'middle_if'
ON DUPLICATE KEY UPDATE time_value = VALUES(time_value);

-- Flare time to ground
INSERT INTO time_to_ground (contact_type_id, distance_zone_id, time_value)
SELECT ct.id, dz.id, 3 FROM contact_types ct, distance_zones dz WHERE ct.name = 'flare' AND dz.name = 'middle_of'
ON DUPLICATE KEY UPDATE time_value = VALUES(time_value);
INSERT INTO time_to_ground (contact_type_id, distance_zone_id, time_value)
SELECT ct.id, dz.id, 2 FROM contact_types ct, distance_zones dz WHERE ct.name = 'flare' AND dz.name = 'shallow_of'
ON DUPLICATE KEY UPDATE time_value = VALUES(time_value);
INSERT INTO time_to_ground (contact_type_id, distance_zone_id, time_value)
SELECT ct.id, dz.id, 2 FROM contact_types ct, distance_zones dz WHERE ct.name = 'flare' AND dz.name = 'deep_if'
ON DUPLICATE KEY UPDATE time_value = VALUES(time_value);
INSERT INTO time_to_ground (contact_type_id, distance_zone_id, time_value)
SELECT ct.id, dz.id, 1 FROM contact_types ct, distance_zones dz WHERE ct.name = 'flare' AND dz.name = 'middle_if'
ON DUPLICATE KEY UPDATE time_value = VALUES(time_value);
INSERT INTO time_to_ground (contact_type_id, distance_zone_id, time_value)
SELECT ct.id, dz.id, 1 FROM contact_types ct, distance_zones dz WHERE ct.name = 'flare' AND dz.name = 'shallow_if'
ON DUPLICATE KEY UPDATE time_value = VALUES(time_value);

-- Burner time to ground
INSERT INTO time_to_ground (contact_type_id, distance_zone_id, time_value)
SELECT ct.id, dz.id, 3 FROM contact_types ct, distance_zones dz WHERE ct.name = 'burner' AND dz.name = 'shallow_of'
ON DUPLICATE KEY UPDATE time_value = VALUES(time_value);
INSERT INTO time_to_ground (contact_type_id, distance_zone_id, time_value)
SELECT ct.id, dz.id, 2 FROM contact_types ct, distance_zones dz WHERE ct.name = 'burner' AND dz.name = 'deep_if'
ON DUPLICATE KEY UPDATE time_value = VALUES(time_value);
INSERT INTO time_to_ground (contact_type_id, distance_zone_id, time_value)
SELECT ct.id, dz.id, 1 FROM contact_types ct, distance_zones dz WHERE ct.name = 'burner' AND dz.name = 'middle_if'
ON DUPLICATE KEY UPDATE time_value = VALUES(time_value);
INSERT INTO time_to_ground (contact_type_id, distance_zone_id, time_value)
SELECT ct.id, dz.id, 1 FROM contact_types ct, distance_zones dz WHERE ct.name = 'burner' AND dz.name = 'shallow_if'
ON DUPLICATE KEY UPDATE time_value = VALUES(time_value);

-- Under time to ground
INSERT INTO time_to_ground (contact_type_id, distance_zone_id, time_value)
SELECT ct.id, dz.id, 4 FROM contact_types ct, distance_zones dz WHERE ct.name = 'under' AND dz.name = 'shallow_of'
ON DUPLICATE KEY UPDATE time_value = VALUES(time_value);
INSERT INTO time_to_ground (contact_type_id, distance_zone_id, time_value)
SELECT ct.id, dz.id, 3 FROM contact_types ct, distance_zones dz WHERE ct.name = 'under' AND dz.name = 'deep_if'
ON DUPLICATE KEY UPDATE time_value = VALUES(time_value);
INSERT INTO time_to_ground (contact_type_id, distance_zone_id, time_value)
SELECT ct.id, dz.id, 2 FROM contact_types ct, distance_zones dz WHERE ct.name = 'under' AND dz.name = 'middle_if'
ON DUPLICATE KEY UPDATE time_value = VALUES(time_value);
INSERT INTO time_to_ground (contact_type_id, distance_zone_id, time_value)
SELECT ct.id, dz.id, 1 FROM contact_types ct, distance_zones dz WHERE ct.name = 'under' AND dz.name = 'shallow_if'
ON DUPLICATE KEY UPDATE time_value = VALUES(time_value);
INSERT INTO time_to_ground (contact_type_id, distance_zone_id, time_value)
SELECT ct.id, dz.id, 1 FROM contact_types ct, distance_zones dz WHERE ct.name = 'under' AND dz.name = 'mound'
ON DUPLICATE KEY UPDATE time_value = VALUES(time_value);
INSERT INTO time_to_ground (contact_type_id, distance_zone_id, time_value)
SELECT ct.id, dz.id, 1 FROM contact_types ct, distance_zones dz WHERE ct.name = 'under' AND dz.name = 'catcher'
ON DUPLICATE KEY UPDATE time_value = VALUES(time_value);

-- Topped time to ground
INSERT INTO time_to_ground (contact_type_id, distance_zone_id, time_value)
SELECT ct.id, dz.id, 1 FROM contact_types ct, distance_zones dz WHERE ct.name = 'topped' AND dz.name = 'middle_if'
ON DUPLICATE KEY UPDATE time_value = VALUES(time_value);
INSERT INTO time_to_ground (contact_type_id, distance_zone_id, time_value)
SELECT ct.id, dz.id, 1 FROM contact_types ct, distance_zones dz WHERE ct.name = 'topped' AND dz.name = 'shallow_if'
ON DUPLICATE KEY UPDATE time_value = VALUES(time_value);
INSERT INTO time_to_ground (contact_type_id, distance_zone_id, time_value)
SELECT ct.id, dz.id, 1 FROM contact_types ct, distance_zones dz WHERE ct.name = 'topped' AND dz.name = 'mound'
ON DUPLICATE KEY UPDATE time_value = VALUES(time_value);
INSERT INTO time_to_ground (contact_type_id, distance_zone_id, time_value)
SELECT ct.id, dz.id, 1 FROM contact_types ct, distance_zones dz WHERE ct.name = 'topped' AND dz.name = 'catcher'
ON DUPLICATE KEY UPDATE time_value = VALUES(time_value);

-- Weak time to ground
INSERT INTO time_to_ground (contact_type_id, distance_zone_id, time_value)
SELECT ct.id, dz.id, 1 FROM contact_types ct, distance_zones dz WHERE ct.name = 'weak' AND dz.name = 'shallow_if'
ON DUPLICATE KEY UPDATE time_value = VALUES(time_value);
INSERT INTO time_to_ground (contact_type_id, distance_zone_id, time_value)
SELECT ct.id, dz.id, 1 FROM contact_types ct, distance_zones dz WHERE ct.name = 'weak' AND dz.name = 'mound'
ON DUPLICATE KEY UPDATE time_value = VALUES(time_value);
INSERT INTO time_to_ground (contact_type_id, distance_zone_id, time_value)
SELECT ct.id, dz.id, 1 FROM contact_types ct, distance_zones dz WHERE ct.name = 'weak' AND dz.name = 'catcher'
ON DUPLICATE KEY UPDATE time_value = VALUES(time_value);


-- 2.4 Fielding Modifier - Air vs ground ball modifiers
CREATE TABLE IF NOT EXISTS fielding_modifier (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    ball_type ENUM('air', 'ground') NOT NULL,
    zone_type ENUM('infield', 'outfield') NOT NULL,
    fielding_outcome_id INT UNSIGNED NOT NULL,
    modifier_value INT NOT NULL,

    UNIQUE KEY uk_modifier (ball_type, zone_type, fielding_outcome_id),

    FOREIGN KEY (fielding_outcome_id) REFERENCES fielding_outcomes(id)
);

-- Air ball modifiers
INSERT INTO fielding_modifier (ball_type, zone_type, fielding_outcome_id, modifier_value)
SELECT 'air', 'infield', fo.id, 2 FROM fielding_outcomes fo WHERE fo.name = 'out'
ON DUPLICATE KEY UPDATE modifier_value = VALUES(modifier_value);
INSERT INTO fielding_modifier (ball_type, zone_type, fielding_outcome_id, modifier_value)
SELECT 'air', 'infield', fo.id, 2 FROM fielding_outcomes fo WHERE fo.name = 'single'
ON DUPLICATE KEY UPDATE modifier_value = VALUES(modifier_value);
INSERT INTO fielding_modifier (ball_type, zone_type, fielding_outcome_id, modifier_value)
SELECT 'air', 'infield', fo.id, 3 FROM fielding_outcomes fo WHERE fo.name = 'double'
ON DUPLICATE KEY UPDATE modifier_value = VALUES(modifier_value);
INSERT INTO fielding_modifier (ball_type, zone_type, fielding_outcome_id, modifier_value)
SELECT 'air', 'infield', fo.id, 0 FROM fielding_outcomes fo WHERE fo.name = 'triple'
ON DUPLICATE KEY UPDATE modifier_value = VALUES(modifier_value);

INSERT INTO fielding_modifier (ball_type, zone_type, fielding_outcome_id, modifier_value)
SELECT 'air', 'outfield', fo.id, 3 FROM fielding_outcomes fo WHERE fo.name = 'out'
ON DUPLICATE KEY UPDATE modifier_value = VALUES(modifier_value);
INSERT INTO fielding_modifier (ball_type, zone_type, fielding_outcome_id, modifier_value)
SELECT 'air', 'outfield', fo.id, 1 FROM fielding_outcomes fo WHERE fo.name = 'single'
ON DUPLICATE KEY UPDATE modifier_value = VALUES(modifier_value);
INSERT INTO fielding_modifier (ball_type, zone_type, fielding_outcome_id, modifier_value)
SELECT 'air', 'outfield', fo.id, 5 FROM fielding_outcomes fo WHERE fo.name = 'double'
ON DUPLICATE KEY UPDATE modifier_value = VALUES(modifier_value);
INSERT INTO fielding_modifier (ball_type, zone_type, fielding_outcome_id, modifier_value)
SELECT 'air', 'outfield', fo.id, 2 FROM fielding_outcomes fo WHERE fo.name = 'triple'
ON DUPLICATE KEY UPDATE modifier_value = VALUES(modifier_value);

-- Ground ball modifiers
INSERT INTO fielding_modifier (ball_type, zone_type, fielding_outcome_id, modifier_value)
SELECT 'ground', 'infield', fo.id, 1 FROM fielding_outcomes fo WHERE fo.name = 'out'
ON DUPLICATE KEY UPDATE modifier_value = VALUES(modifier_value);
INSERT INTO fielding_modifier (ball_type, zone_type, fielding_outcome_id, modifier_value)
SELECT 'ground', 'infield', fo.id, 5 FROM fielding_outcomes fo WHERE fo.name = 'single'
ON DUPLICATE KEY UPDATE modifier_value = VALUES(modifier_value);
INSERT INTO fielding_modifier (ball_type, zone_type, fielding_outcome_id, modifier_value)
SELECT 'ground', 'infield', fo.id, 1 FROM fielding_outcomes fo WHERE fo.name = 'double'
ON DUPLICATE KEY UPDATE modifier_value = VALUES(modifier_value);
INSERT INTO fielding_modifier (ball_type, zone_type, fielding_outcome_id, modifier_value)
SELECT 'ground', 'infield', fo.id, 1 FROM fielding_outcomes fo WHERE fo.name = 'triple'
ON DUPLICATE KEY UPDATE modifier_value = VALUES(modifier_value);

INSERT INTO fielding_modifier (ball_type, zone_type, fielding_outcome_id, modifier_value)
SELECT 'ground', 'outfield', fo.id, 2 FROM fielding_outcomes fo WHERE fo.name = 'out'
ON DUPLICATE KEY UPDATE modifier_value = VALUES(modifier_value);
INSERT INTO fielding_modifier (ball_type, zone_type, fielding_outcome_id, modifier_value)
SELECT 'ground', 'outfield', fo.id, 2 FROM fielding_outcomes fo WHERE fo.name = 'single'
ON DUPLICATE KEY UPDATE modifier_value = VALUES(modifier_value);
INSERT INTO fielding_modifier (ball_type, zone_type, fielding_outcome_id, modifier_value)
SELECT 'ground', 'outfield', fo.id, 3 FROM fielding_outcomes fo WHERE fo.name = 'double'
ON DUPLICATE KEY UPDATE modifier_value = VALUES(modifier_value);
INSERT INTO fielding_modifier (ball_type, zone_type, fielding_outcome_id, modifier_value)
SELECT 'ground', 'outfield', fo.id, 3 FROM fielding_outcomes fo WHERE fo.name = 'triple'
ON DUPLICATE KEY UPDATE modifier_value = VALUES(modifier_value);


-- -----------------------------------------------------------------------------
-- PHASE 3: Level-Specific Tables
-- -----------------------------------------------------------------------------

-- 3.1 Level Contact Odds - Contact type probabilities per level
CREATE TABLE IF NOT EXISTS level_contact_odds (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    league_level INT UNSIGNED NOT NULL,
    contact_type_id INT UNSIGNED NOT NULL,
    odds FLOAT NOT NULL,

    UNIQUE KEY uk_level_contact (league_level, contact_type_id),
    INDEX idx_level (league_level),

    FOREIGN KEY (contact_type_id) REFERENCES contact_types(id)
);

-- Insert default MLB (level 9) contact odds
INSERT INTO level_contact_odds (league_level, contact_type_id, odds)
SELECT 9, ct.id, 7.0 FROM contact_types ct WHERE ct.name = 'barrel'
ON DUPLICATE KEY UPDATE odds = VALUES(odds);
INSERT INTO level_contact_odds (league_level, contact_type_id, odds)
SELECT 9, ct.id, 12.0 FROM contact_types ct WHERE ct.name = 'solid'
ON DUPLICATE KEY UPDATE odds = VALUES(odds);
INSERT INTO level_contact_odds (league_level, contact_type_id, odds)
SELECT 9, ct.id, 36.0 FROM contact_types ct WHERE ct.name = 'flare'
ON DUPLICATE KEY UPDATE odds = VALUES(odds);
INSERT INTO level_contact_odds (league_level, contact_type_id, odds)
SELECT 9, ct.id, 39.0 FROM contact_types ct WHERE ct.name = 'burner'
ON DUPLICATE KEY UPDATE odds = VALUES(odds);
INSERT INTO level_contact_odds (league_level, contact_type_id, odds)
SELECT 9, ct.id, 2.4 FROM contact_types ct WHERE ct.name = 'under'
ON DUPLICATE KEY UPDATE odds = VALUES(odds);
INSERT INTO level_contact_odds (league_level, contact_type_id, odds)
SELECT 9, ct.id, 3.2 FROM contact_types ct WHERE ct.name = 'topped'
ON DUPLICATE KEY UPDATE odds = VALUES(odds);
INSERT INTO level_contact_odds (league_level, contact_type_id, odds)
SELECT 9, ct.id, 0.4 FROM contact_types ct WHERE ct.name = 'weak'
ON DUPLICATE KEY UPDATE odds = VALUES(odds);


-- 3.2 Level Batting Config - Swing/contact rates per level
CREATE TABLE IF NOT EXISTS level_batting_config (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    league_level INT UNSIGNED NOT NULL UNIQUE,

    inside_swing FLOAT NOT NULL DEFAULT 0.65,
    outside_swing FLOAT NOT NULL DEFAULT 0.30,
    inside_contact FLOAT NOT NULL DEFAULT 0.87,
    outside_contact FLOAT NOT NULL DEFAULT 0.66,
    modexp FLOAT NOT NULL DEFAULT 2.0,

    INDEX idx_level (league_level)
);

-- Insert default MLB (level 9) batting config
INSERT INTO level_batting_config (league_level, inside_swing, outside_swing, inside_contact, outside_contact, modexp)
VALUES (9, 0.65, 0.30, 0.87, 0.66, 2.0)
ON DUPLICATE KEY UPDATE inside_swing = VALUES(inside_swing);


-- 3.3 Level Game Config - Other level-specific settings
CREATE TABLE IF NOT EXISTS level_game_config (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    league_level INT UNSIGNED NOT NULL UNIQUE,

    error_rate FLOAT NOT NULL DEFAULT 0.05,
    steal_success FLOAT NOT NULL DEFAULT 0.65,
    pickoff_success FLOAT NOT NULL DEFAULT 0.10,

    pregame_injury_base_rate FLOAT NOT NULL DEFAULT 0.10,
    ingame_injury_base_rate FLOAT NOT NULL DEFAULT 0.10,

    energy_tick_cap FLOAT NOT NULL DEFAULT 1.5,
    energy_step FLOAT NOT NULL DEFAULT 2.0,
    short_leash FLOAT NOT NULL DEFAULT 0.8,
    normal_leash FLOAT NOT NULL DEFAULT 0.7,
    long_leash FLOAT NOT NULL DEFAULT 0.5,
    fielding_multiplier FLOAT NOT NULL DEFAULT 0.0,

    INDEX idx_level (league_level)
);

-- Insert default MLB (level 9) game config
INSERT INTO level_game_config (
    league_level, error_rate, steal_success, pickoff_success,
    pregame_injury_base_rate, ingame_injury_base_rate,
    energy_tick_cap, energy_step, short_leash, normal_leash, long_leash, fielding_multiplier
)
VALUES (9, 0.05, 0.65, 0.10, 0.10, 0.10, 1.5, 2.0, 0.8, 0.7, 0.5, 0.0)
ON DUPLICATE KEY UPDATE error_rate = VALUES(error_rate);


-- 3.4 Level Distance Weights - Distance distribution by contact type per level
CREATE TABLE IF NOT EXISTS level_distance_weights (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    league_level INT UNSIGNED NOT NULL,
    contact_type_id INT UNSIGNED NOT NULL,
    distance_zone_id INT UNSIGNED NOT NULL,
    weight FLOAT NOT NULL,

    UNIQUE KEY uk_level_dist (league_level, contact_type_id, distance_zone_id),
    INDEX idx_level (league_level),

    FOREIGN KEY (contact_type_id) REFERENCES contact_types(id),
    FOREIGN KEY (distance_zone_id) REFERENCES distance_zones(id)
);

-- Insert default MLB (level 9) distance weights
-- Barrel: [0.20, 0.45, 0.25, 0.10, 0.00, 0.00, 0.00, 0.00, 0.00]
INSERT INTO level_distance_weights (league_level, contact_type_id, distance_zone_id, weight)
SELECT 9, ct.id, dz.id, 0.20 FROM contact_types ct, distance_zones dz WHERE ct.name = 'barrel' AND dz.name = 'homerun'
ON DUPLICATE KEY UPDATE weight = VALUES(weight);
INSERT INTO level_distance_weights (league_level, contact_type_id, distance_zone_id, weight)
SELECT 9, ct.id, dz.id, 0.45 FROM contact_types ct, distance_zones dz WHERE ct.name = 'barrel' AND dz.name = 'deep_of'
ON DUPLICATE KEY UPDATE weight = VALUES(weight);
INSERT INTO level_distance_weights (league_level, contact_type_id, distance_zone_id, weight)
SELECT 9, ct.id, dz.id, 0.25 FROM contact_types ct, distance_zones dz WHERE ct.name = 'barrel' AND dz.name = 'middle_of'
ON DUPLICATE KEY UPDATE weight = VALUES(weight);
INSERT INTO level_distance_weights (league_level, contact_type_id, distance_zone_id, weight)
SELECT 9, ct.id, dz.id, 0.10 FROM contact_types ct, distance_zones dz WHERE ct.name = 'barrel' AND dz.name = 'shallow_of'
ON DUPLICATE KEY UPDATE weight = VALUES(weight);

-- Solid: [0.05, 0.20, 0.25, 0.20, 0.15, 0.10, 0.00, 0.00, 0.00]
INSERT INTO level_distance_weights (league_level, contact_type_id, distance_zone_id, weight)
SELECT 9, ct.id, dz.id, 0.05 FROM contact_types ct, distance_zones dz WHERE ct.name = 'solid' AND dz.name = 'homerun'
ON DUPLICATE KEY UPDATE weight = VALUES(weight);
INSERT INTO level_distance_weights (league_level, contact_type_id, distance_zone_id, weight)
SELECT 9, ct.id, dz.id, 0.20 FROM contact_types ct, distance_zones dz WHERE ct.name = 'solid' AND dz.name = 'deep_of'
ON DUPLICATE KEY UPDATE weight = VALUES(weight);
INSERT INTO level_distance_weights (league_level, contact_type_id, distance_zone_id, weight)
SELECT 9, ct.id, dz.id, 0.25 FROM contact_types ct, distance_zones dz WHERE ct.name = 'solid' AND dz.name = 'middle_of'
ON DUPLICATE KEY UPDATE weight = VALUES(weight);
INSERT INTO level_distance_weights (league_level, contact_type_id, distance_zone_id, weight)
SELECT 9, ct.id, dz.id, 0.20 FROM contact_types ct, distance_zones dz WHERE ct.name = 'solid' AND dz.name = 'shallow_of'
ON DUPLICATE KEY UPDATE weight = VALUES(weight);
INSERT INTO level_distance_weights (league_level, contact_type_id, distance_zone_id, weight)
SELECT 9, ct.id, dz.id, 0.15 FROM contact_types ct, distance_zones dz WHERE ct.name = 'solid' AND dz.name = 'deep_if'
ON DUPLICATE KEY UPDATE weight = VALUES(weight);
INSERT INTO level_distance_weights (league_level, contact_type_id, distance_zone_id, weight)
SELECT 9, ct.id, dz.id, 0.10 FROM contact_types ct, distance_zones dz WHERE ct.name = 'solid' AND dz.name = 'middle_if'
ON DUPLICATE KEY UPDATE weight = VALUES(weight);

-- Flare: [0.00, 0.00, 0.25, 0.35, 0.25, 0.10, 0.05, 0.00, 0.00]
INSERT INTO level_distance_weights (league_level, contact_type_id, distance_zone_id, weight)
SELECT 9, ct.id, dz.id, 0.25 FROM contact_types ct, distance_zones dz WHERE ct.name = 'flare' AND dz.name = 'middle_of'
ON DUPLICATE KEY UPDATE weight = VALUES(weight);
INSERT INTO level_distance_weights (league_level, contact_type_id, distance_zone_id, weight)
SELECT 9, ct.id, dz.id, 0.35 FROM contact_types ct, distance_zones dz WHERE ct.name = 'flare' AND dz.name = 'shallow_of'
ON DUPLICATE KEY UPDATE weight = VALUES(weight);
INSERT INTO level_distance_weights (league_level, contact_type_id, distance_zone_id, weight)
SELECT 9, ct.id, dz.id, 0.25 FROM contact_types ct, distance_zones dz WHERE ct.name = 'flare' AND dz.name = 'deep_if'
ON DUPLICATE KEY UPDATE weight = VALUES(weight);
INSERT INTO level_distance_weights (league_level, contact_type_id, distance_zone_id, weight)
SELECT 9, ct.id, dz.id, 0.10 FROM contact_types ct, distance_zones dz WHERE ct.name = 'flare' AND dz.name = 'middle_if'
ON DUPLICATE KEY UPDATE weight = VALUES(weight);
INSERT INTO level_distance_weights (league_level, contact_type_id, distance_zone_id, weight)
SELECT 9, ct.id, dz.id, 0.05 FROM contact_types ct, distance_zones dz WHERE ct.name = 'flare' AND dz.name = 'shallow_if'
ON DUPLICATE KEY UPDATE weight = VALUES(weight);

-- Burner: [0.00, 0.00, 0.00, 0.00, 0.20, 0.60, 0.20, 0.00, 0.00]
INSERT INTO level_distance_weights (league_level, contact_type_id, distance_zone_id, weight)
SELECT 9, ct.id, dz.id, 0.20 FROM contact_types ct, distance_zones dz WHERE ct.name = 'burner' AND dz.name = 'deep_if'
ON DUPLICATE KEY UPDATE weight = VALUES(weight);
INSERT INTO level_distance_weights (league_level, contact_type_id, distance_zone_id, weight)
SELECT 9, ct.id, dz.id, 0.60 FROM contact_types ct, distance_zones dz WHERE ct.name = 'burner' AND dz.name = 'middle_if'
ON DUPLICATE KEY UPDATE weight = VALUES(weight);
INSERT INTO level_distance_weights (league_level, contact_type_id, distance_zone_id, weight)
SELECT 9, ct.id, dz.id, 0.20 FROM contact_types ct, distance_zones dz WHERE ct.name = 'burner' AND dz.name = 'shallow_if'
ON DUPLICATE KEY UPDATE weight = VALUES(weight);

-- Under: [0.00, 0.00, 0.00, 0.05, 0.15, 0.25, 0.35, 0.15, 0.05]
INSERT INTO level_distance_weights (league_level, contact_type_id, distance_zone_id, weight)
SELECT 9, ct.id, dz.id, 0.05 FROM contact_types ct, distance_zones dz WHERE ct.name = 'under' AND dz.name = 'shallow_of'
ON DUPLICATE KEY UPDATE weight = VALUES(weight);
INSERT INTO level_distance_weights (league_level, contact_type_id, distance_zone_id, weight)
SELECT 9, ct.id, dz.id, 0.15 FROM contact_types ct, distance_zones dz WHERE ct.name = 'under' AND dz.name = 'deep_if'
ON DUPLICATE KEY UPDATE weight = VALUES(weight);
INSERT INTO level_distance_weights (league_level, contact_type_id, distance_zone_id, weight)
SELECT 9, ct.id, dz.id, 0.25 FROM contact_types ct, distance_zones dz WHERE ct.name = 'under' AND dz.name = 'middle_if'
ON DUPLICATE KEY UPDATE weight = VALUES(weight);
INSERT INTO level_distance_weights (league_level, contact_type_id, distance_zone_id, weight)
SELECT 9, ct.id, dz.id, 0.35 FROM contact_types ct, distance_zones dz WHERE ct.name = 'under' AND dz.name = 'shallow_if'
ON DUPLICATE KEY UPDATE weight = VALUES(weight);
INSERT INTO level_distance_weights (league_level, contact_type_id, distance_zone_id, weight)
SELECT 9, ct.id, dz.id, 0.15 FROM contact_types ct, distance_zones dz WHERE ct.name = 'under' AND dz.name = 'mound'
ON DUPLICATE KEY UPDATE weight = VALUES(weight);
INSERT INTO level_distance_weights (league_level, contact_type_id, distance_zone_id, weight)
SELECT 9, ct.id, dz.id, 0.05 FROM contact_types ct, distance_zones dz WHERE ct.name = 'under' AND dz.name = 'catcher'
ON DUPLICATE KEY UPDATE weight = VALUES(weight);

-- Topped: [0.00, 0.00, 0.00, 0.00, 0.00, 0.20, 0.40, 0.30, 0.10]
INSERT INTO level_distance_weights (league_level, contact_type_id, distance_zone_id, weight)
SELECT 9, ct.id, dz.id, 0.20 FROM contact_types ct, distance_zones dz WHERE ct.name = 'topped' AND dz.name = 'middle_if'
ON DUPLICATE KEY UPDATE weight = VALUES(weight);
INSERT INTO level_distance_weights (league_level, contact_type_id, distance_zone_id, weight)
SELECT 9, ct.id, dz.id, 0.40 FROM contact_types ct, distance_zones dz WHERE ct.name = 'topped' AND dz.name = 'shallow_if'
ON DUPLICATE KEY UPDATE weight = VALUES(weight);
INSERT INTO level_distance_weights (league_level, contact_type_id, distance_zone_id, weight)
SELECT 9, ct.id, dz.id, 0.30 FROM contact_types ct, distance_zones dz WHERE ct.name = 'topped' AND dz.name = 'mound'
ON DUPLICATE KEY UPDATE weight = VALUES(weight);
INSERT INTO level_distance_weights (league_level, contact_type_id, distance_zone_id, weight)
SELECT 9, ct.id, dz.id, 0.10 FROM contact_types ct, distance_zones dz WHERE ct.name = 'topped' AND dz.name = 'catcher'
ON DUPLICATE KEY UPDATE weight = VALUES(weight);

-- Weak: [0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.30, 0.40, 0.30]
INSERT INTO level_distance_weights (league_level, contact_type_id, distance_zone_id, weight)
SELECT 9, ct.id, dz.id, 0.30 FROM contact_types ct, distance_zones dz WHERE ct.name = 'weak' AND dz.name = 'shallow_if'
ON DUPLICATE KEY UPDATE weight = VALUES(weight);
INSERT INTO level_distance_weights (league_level, contact_type_id, distance_zone_id, weight)
SELECT 9, ct.id, dz.id, 0.40 FROM contact_types ct, distance_zones dz WHERE ct.name = 'weak' AND dz.name = 'mound'
ON DUPLICATE KEY UPDATE weight = VALUES(weight);
INSERT INTO level_distance_weights (league_level, contact_type_id, distance_zone_id, weight)
SELECT 9, ct.id, dz.id, 0.30 FROM contact_types ct, distance_zones dz WHERE ct.name = 'weak' AND dz.name = 'catcher'
ON DUPLICATE KEY UPDATE weight = VALUES(weight);


-- 3.5 Level Fielding Weights - Out/hit probabilities by contact type per level
CREATE TABLE IF NOT EXISTS level_fielding_weights (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    league_level INT UNSIGNED NOT NULL,
    contact_type_id INT UNSIGNED NOT NULL,
    fielding_outcome_id INT UNSIGNED NOT NULL,
    weight FLOAT NOT NULL,

    UNIQUE KEY uk_level_field (league_level, contact_type_id, fielding_outcome_id),
    INDEX idx_level (league_level),

    FOREIGN KEY (contact_type_id) REFERENCES contact_types(id),
    FOREIGN KEY (fielding_outcome_id) REFERENCES fielding_outcomes(id)
);

-- Insert default MLB (level 9) fielding weights
-- Barrel: [0.25, 0.28, 0.10, 0.05] (out, single, double, triple - missing values become HR)
INSERT INTO level_fielding_weights (league_level, contact_type_id, fielding_outcome_id, weight)
SELECT 9, ct.id, fo.id, 0.25 FROM contact_types ct, fielding_outcomes fo WHERE ct.name = 'barrel' AND fo.name = 'out'
ON DUPLICATE KEY UPDATE weight = VALUES(weight);
INSERT INTO level_fielding_weights (league_level, contact_type_id, fielding_outcome_id, weight)
SELECT 9, ct.id, fo.id, 0.28 FROM contact_types ct, fielding_outcomes fo WHERE ct.name = 'barrel' AND fo.name = 'single'
ON DUPLICATE KEY UPDATE weight = VALUES(weight);
INSERT INTO level_fielding_weights (league_level, contact_type_id, fielding_outcome_id, weight)
SELECT 9, ct.id, fo.id, 0.10 FROM contact_types ct, fielding_outcomes fo WHERE ct.name = 'barrel' AND fo.name = 'double'
ON DUPLICATE KEY UPDATE weight = VALUES(weight);
INSERT INTO level_fielding_weights (league_level, contact_type_id, fielding_outcome_id, weight)
SELECT 9, ct.id, fo.id, 0.05 FROM contact_types ct, fielding_outcomes fo WHERE ct.name = 'barrel' AND fo.name = 'triple'
ON DUPLICATE KEY UPDATE weight = VALUES(weight);

-- Solid: [0.72, 0.20, 0.15, 0.01]
INSERT INTO level_fielding_weights (league_level, contact_type_id, fielding_outcome_id, weight)
SELECT 9, ct.id, fo.id, 0.72 FROM contact_types ct, fielding_outcomes fo WHERE ct.name = 'solid' AND fo.name = 'out'
ON DUPLICATE KEY UPDATE weight = VALUES(weight);
INSERT INTO level_fielding_weights (league_level, contact_type_id, fielding_outcome_id, weight)
SELECT 9, ct.id, fo.id, 0.20 FROM contact_types ct, fielding_outcomes fo WHERE ct.name = 'solid' AND fo.name = 'single'
ON DUPLICATE KEY UPDATE weight = VALUES(weight);
INSERT INTO level_fielding_weights (league_level, contact_type_id, fielding_outcome_id, weight)
SELECT 9, ct.id, fo.id, 0.15 FROM contact_types ct, fielding_outcomes fo WHERE ct.name = 'solid' AND fo.name = 'double'
ON DUPLICATE KEY UPDATE weight = VALUES(weight);
INSERT INTO level_fielding_weights (league_level, contact_type_id, fielding_outcome_id, weight)
SELECT 9, ct.id, fo.id, 0.01 FROM contact_types ct, fielding_outcomes fo WHERE ct.name = 'solid' AND fo.name = 'triple'
ON DUPLICATE KEY UPDATE weight = VALUES(weight);

-- Flare: [0.52, 0.28, 0.20, 0.00]
INSERT INTO level_fielding_weights (league_level, contact_type_id, fielding_outcome_id, weight)
SELECT 9, ct.id, fo.id, 0.52 FROM contact_types ct, fielding_outcomes fo WHERE ct.name = 'flare' AND fo.name = 'out'
ON DUPLICATE KEY UPDATE weight = VALUES(weight);
INSERT INTO level_fielding_weights (league_level, contact_type_id, fielding_outcome_id, weight)
SELECT 9, ct.id, fo.id, 0.28 FROM contact_types ct, fielding_outcomes fo WHERE ct.name = 'flare' AND fo.name = 'single'
ON DUPLICATE KEY UPDATE weight = VALUES(weight);
INSERT INTO level_fielding_weights (league_level, contact_type_id, fielding_outcome_id, weight)
SELECT 9, ct.id, fo.id, 0.20 FROM contact_types ct, fielding_outcomes fo WHERE ct.name = 'flare' AND fo.name = 'double'
ON DUPLICATE KEY UPDATE weight = VALUES(weight);
INSERT INTO level_fielding_weights (league_level, contact_type_id, fielding_outcome_id, weight)
SELECT 9, ct.id, fo.id, 0.00 FROM contact_types ct, fielding_outcomes fo WHERE ct.name = 'flare' AND fo.name = 'triple'
ON DUPLICATE KEY UPDATE weight = VALUES(weight);

-- Burner: [0.52, 0.38, 0.10, 0.00]
INSERT INTO level_fielding_weights (league_level, contact_type_id, fielding_outcome_id, weight)
SELECT 9, ct.id, fo.id, 0.52 FROM contact_types ct, fielding_outcomes fo WHERE ct.name = 'burner' AND fo.name = 'out'
ON DUPLICATE KEY UPDATE weight = VALUES(weight);
INSERT INTO level_fielding_weights (league_level, contact_type_id, fielding_outcome_id, weight)
SELECT 9, ct.id, fo.id, 0.38 FROM contact_types ct, fielding_outcomes fo WHERE ct.name = 'burner' AND fo.name = 'single'
ON DUPLICATE KEY UPDATE weight = VALUES(weight);
INSERT INTO level_fielding_weights (league_level, contact_type_id, fielding_outcome_id, weight)
SELECT 9, ct.id, fo.id, 0.10 FROM contact_types ct, fielding_outcomes fo WHERE ct.name = 'burner' AND fo.name = 'double'
ON DUPLICATE KEY UPDATE weight = VALUES(weight);
INSERT INTO level_fielding_weights (league_level, contact_type_id, fielding_outcome_id, weight)
SELECT 9, ct.id, fo.id, 0.00 FROM contact_types ct, fielding_outcomes fo WHERE ct.name = 'burner' AND fo.name = 'triple'
ON DUPLICATE KEY UPDATE weight = VALUES(weight);

-- Under: [0.92, 0.08, 0.00, 0.00]
INSERT INTO level_fielding_weights (league_level, contact_type_id, fielding_outcome_id, weight)
SELECT 9, ct.id, fo.id, 0.92 FROM contact_types ct, fielding_outcomes fo WHERE ct.name = 'under' AND fo.name = 'out'
ON DUPLICATE KEY UPDATE weight = VALUES(weight);
INSERT INTO level_fielding_weights (league_level, contact_type_id, fielding_outcome_id, weight)
SELECT 9, ct.id, fo.id, 0.08 FROM contact_types ct, fielding_outcomes fo WHERE ct.name = 'under' AND fo.name = 'single'
ON DUPLICATE KEY UPDATE weight = VALUES(weight);
INSERT INTO level_fielding_weights (league_level, contact_type_id, fielding_outcome_id, weight)
SELECT 9, ct.id, fo.id, 0.00 FROM contact_types ct, fielding_outcomes fo WHERE ct.name = 'under' AND fo.name = 'double'
ON DUPLICATE KEY UPDATE weight = VALUES(weight);
INSERT INTO level_fielding_weights (league_level, contact_type_id, fielding_outcome_id, weight)
SELECT 9, ct.id, fo.id, 0.00 FROM contact_types ct, fielding_outcomes fo WHERE ct.name = 'under' AND fo.name = 'triple'
ON DUPLICATE KEY UPDATE weight = VALUES(weight);

-- Topped: [0.88, 0.12, 0.00, 0.00]
INSERT INTO level_fielding_weights (league_level, contact_type_id, fielding_outcome_id, weight)
SELECT 9, ct.id, fo.id, 0.88 FROM contact_types ct, fielding_outcomes fo WHERE ct.name = 'topped' AND fo.name = 'out'
ON DUPLICATE KEY UPDATE weight = VALUES(weight);
INSERT INTO level_fielding_weights (league_level, contact_type_id, fielding_outcome_id, weight)
SELECT 9, ct.id, fo.id, 0.12 FROM contact_types ct, fielding_outcomes fo WHERE ct.name = 'topped' AND fo.name = 'single'
ON DUPLICATE KEY UPDATE weight = VALUES(weight);
INSERT INTO level_fielding_weights (league_level, contact_type_id, fielding_outcome_id, weight)
SELECT 9, ct.id, fo.id, 0.00 FROM contact_types ct, fielding_outcomes fo WHERE ct.name = 'topped' AND fo.name = 'double'
ON DUPLICATE KEY UPDATE weight = VALUES(weight);
INSERT INTO level_fielding_weights (league_level, contact_type_id, fielding_outcome_id, weight)
SELECT 9, ct.id, fo.id, 0.00 FROM contact_types ct, fielding_outcomes fo WHERE ct.name = 'topped' AND fo.name = 'triple'
ON DUPLICATE KEY UPDATE weight = VALUES(weight);

-- Weak: [0.88, 0.12, 0.00, 0.00]
INSERT INTO level_fielding_weights (league_level, contact_type_id, fielding_outcome_id, weight)
SELECT 9, ct.id, fo.id, 0.88 FROM contact_types ct, fielding_outcomes fo WHERE ct.name = 'weak' AND fo.name = 'out'
ON DUPLICATE KEY UPDATE weight = VALUES(weight);
INSERT INTO level_fielding_weights (league_level, contact_type_id, fielding_outcome_id, weight)
SELECT 9, ct.id, fo.id, 0.12 FROM contact_types ct, fielding_outcomes fo WHERE ct.name = 'weak' AND fo.name = 'single'
ON DUPLICATE KEY UPDATE weight = VALUES(weight);
INSERT INTO level_fielding_weights (league_level, contact_type_id, fielding_outcome_id, weight)
SELECT 9, ct.id, fo.id, 0.00 FROM contact_types ct, fielding_outcomes fo WHERE ct.name = 'weak' AND fo.name = 'double'
ON DUPLICATE KEY UPDATE weight = VALUES(weight);
INSERT INTO level_fielding_weights (league_level, contact_type_id, fielding_outcome_id, weight)
SELECT 9, ct.id, fo.id, 0.00 FROM contact_types ct, fielding_outcomes fo WHERE ct.name = 'weak' AND fo.name = 'triple'
ON DUPLICATE KEY UPDATE weight = VALUES(weight);


-- -----------------------------------------------------------------------------
-- PHASE 4: Indexes for Performance
-- -----------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS idx_defensive_alignment_full ON defensive_alignment(field_zone_id, distance_zone_id, position_id);
CREATE INDEX IF NOT EXISTS idx_fielding_difficulty_full ON fielding_difficulty_mapping(field_zone_id, distance_zone_id);
CREATE INDEX IF NOT EXISTS idx_time_to_ground_full ON time_to_ground(contact_type_id, distance_zone_id);
CREATE INDEX IF NOT EXISTS idx_level_contact_odds_full ON level_contact_odds(league_level, contact_type_id);
CREATE INDEX IF NOT EXISTS idx_level_distance_weights_full ON level_distance_weights(league_level, contact_type_id, distance_zone_id);
CREATE INDEX IF NOT EXISTS idx_level_fielding_weights_full ON level_fielding_weights(league_level, contact_type_id, fielding_outcome_id);
