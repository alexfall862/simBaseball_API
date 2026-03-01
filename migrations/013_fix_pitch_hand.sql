-- Migration 013: Regenerate pitch_hand values
--
-- Problem: During initial import, pitch_hand was overwritten with bat_hand,
-- so every player has matching bat/throw (e.g. S/S, R/R, L/L — no cross combos).
--
-- Fix: Reassign pitch_hand using weighted random selection conditioned on bat_hand,
-- matching the generation frequencies from player_engine/constants.py:
--
--   (L,L)=20  (R,R)=60  (L,R)=5  (R,L)=5  (S,L)=5  (S,R)=5
--
-- Conditional probabilities:
--   bat_hand=R → pitch_hand R: 60/65 ≈ 92.3%, L: 5/65 ≈ 7.7%
--   bat_hand=L → pitch_hand L: 20/25 = 80.0%, R: 5/25 = 20.0%
--   bat_hand=S → pitch_hand L: 5/10  = 50.0%, R: 5/10 = 50.0%

SET SQL_SAFE_UPDATES = 0;

-- Right-handed batters: ~7.7% throw lefty
UPDATE simbbPlayers
SET pitch_hand = CASE
    WHEN RAND() < 0.077 THEN 'L'
    ELSE 'R'
END
WHERE bat_hand = 'R';

-- Left-handed batters: ~20% throw righty
UPDATE simbbPlayers
SET pitch_hand = CASE
    WHEN RAND() < 0.20 THEN 'R'
    ELSE 'L'
END
WHERE bat_hand = 'L';

-- Switch hitters: 50/50 throw left or right
UPDATE simbbPlayers
SET pitch_hand = CASE
    WHEN RAND() < 0.50 THEN 'L'
    ELSE 'R'
END
WHERE bat_hand = 'S';

SET SQL_SAFE_UPDATES = 1;
