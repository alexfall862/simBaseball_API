-- A player can be drafted at most once per league year. draft_picks only had
-- a non-unique index on player_id; make_pick() now also row-locks draft_state,
-- this is the belt-and-braces constraint. NULL player_id (unfilled slots) is
-- allowed any number of times by MySQL unique indexes.
ALTER TABLE draft_picks
  ADD UNIQUE KEY uq_dp_player (league_year_id, player_id);
