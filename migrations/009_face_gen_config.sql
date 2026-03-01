-- Migration 009: Face generation config table
-- Stores admin-adjustable probabilities for optional face features.
-- Used by services/face_generator.py when generating player portraits.

CREATE TABLE IF NOT EXISTS face_gen_config (
    id          INT NOT NULL DEFAULT 1 PRIMARY KEY,
    config      JSON NOT NULL,
    updated_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- Seed with facesjs v4.3.3 male defaults
INSERT INTO face_gen_config (id, config) VALUES (1, '{
    "glasses_pct":      0.10,
    "accessories_pct":  0.20,
    "facialHair_pct":   0.50,
    "eyeLine_pct":      0.75,
    "smileLine_pct":    0.75,
    "miscLine_pct":     0.50,
    "hairBg_pct":       0.10
}') ON DUPLICATE KEY UPDATE id = id;
