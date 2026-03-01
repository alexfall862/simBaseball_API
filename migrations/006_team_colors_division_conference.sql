-- 006_team_colors_division_conference.sql
-- Add team branding colors, division, conference, and stadium coordinates.
--
-- MLB usage:
--   conference = 'AL' or 'NL'
--   division   = 'East', 'Central', 'West'
--
-- College usage:
--   conference = conference name (e.g. 'SEC', 'Big Ten')
--   division   = NULL (typically)
--
-- Colors are hex strings (e.g. '#003087') sourced from SimMLB Team Database.xlsx.
-- Stadium coordinates are decimal lat/long.

ALTER TABLE teams
    ADD COLUMN color_one    VARCHAR(7)     DEFAULT NULL AFTER power_mod,
    ADD COLUMN color_two    VARCHAR(7)     DEFAULT NULL AFTER color_one,
    ADD COLUMN color_three  VARCHAR(7)     DEFAULT NULL AFTER color_two,
    ADD COLUMN conference   VARCHAR(50)    DEFAULT NULL AFTER color_three,
    ADD COLUMN division     VARCHAR(50)    DEFAULT NULL AFTER conference,
    ADD COLUMN stadium_lat  DECIMAL(10,6)  DEFAULT NULL AFTER division,
    ADD COLUMN stadium_long DECIMAL(10,6)  DEFAULT NULL AFTER stadium_lat;

-- ============================================================
-- MLB (level 9) — colors, conference, division, coordinates
-- ============================================================

-- AL East
UPDATE teams SET color_one = '#000000', color_two = '#E04400', conference = 'AL', division = 'East',
    stadium_lat = 39.283889, stadium_long = -76.621667 WHERE id = 26;  -- BAL Orioles
UPDATE teams SET color_one = '#BE2C36', color_two = '#052755', conference = 'AL', division = 'East',
    stadium_lat = 42.346250, stadium_long = -71.097750 WHERE id = 20;  -- BOS Red Sox
UPDATE teams SET color_one = '#0B1F46', color_two = '#FFFFFF', conference = 'AL', division = 'East',
    stadium_lat = 40.829167, stadium_long = -73.926389 WHERE id = 5;   -- NYY Yankees
UPDATE teams SET color_one = '#02285C', color_two = '#90BDE7', conference = 'AL', division = 'East',
    stadium_lat = 27.768333, stadium_long = -82.653333 WHERE id = 11;  -- TB Rays
UPDATE teams SET color_one = '#0B498F', color_two = '#17295C', conference = 'AL', division = 'East',
    stadium_lat = 43.641389, stadium_long = -79.389167 WHERE id = 8;   -- TOR Blue Jays

-- AL Central
UPDATE teams SET color_one = '#1E191A', color_two = '#FFFFFF', conference = 'AL', division = 'Central',
    stadium_lat = 41.830000, stadium_long = -87.633889 WHERE id = 16;  -- CWS White Sox
UPDATE teams SET color_one = '#06203F', color_two = '#C90628', conference = 'AL', division = 'Central',
    stadium_lat = 41.495833, stadium_long = -81.685278 WHERE id = 21;  -- CLE Guardians
UPDATE teams SET color_one = '#042855', color_two = '#FF4713', conference = 'AL', division = 'Central',
    stadium_lat = 42.339167, stadium_long = -83.048611 WHERE id = 3;   -- DET Tigers
UPDATE teams SET color_one = '#004488', color_two = '#FFFFFF', conference = 'AL', division = 'Central',
    stadium_lat = 39.051389, stadium_long = -94.480556 WHERE id = 18;  -- KC Royals
UPDATE teams SET color_one = '#E41831', color_two = '#02193E', conference = 'AL', division = 'Central',
    stadium_lat = 44.981667, stadium_long = -93.278333 WHERE id = 19;  -- MIN Twins

-- AL West
UPDATE teams SET color_one = '#002962', color_two = '#EC6E19', conference = 'AL', division = 'West',
    stadium_lat = 29.756944, stadium_long = -95.355556 WHERE id = 4;   -- HOU Astros
UPDATE teams SET color_one = '#CE093F', color_two = '#002E63', conference = 'AL', division = 'West',
    stadium_lat = 33.800278, stadium_long = -117.882778 WHERE id = 12;  -- LAA Angels
UPDATE teams SET color_one = '#00352D', color_two = '#EFB318', conference = 'AL', division = 'West',
    stadium_lat = 37.751667, stadium_long = -122.200556 WHERE id = 14;  -- OAK A's
UPDATE teams SET color_one = '#042855', color_two = '#C5CFD5', conference = 'AL', division = 'West',
    stadium_lat = 47.591000, stadium_long = -122.333000 WHERE id = 25;  -- SEA Mariners
UPDATE teams SET color_one = '#002E79', color_two = '#C10919', conference = 'AL', division = 'West',
    stadium_lat = 32.747361, stadium_long = -97.084167 WHERE id = 2;   -- TEX Rangers

-- NL East
UPDATE teams SET color_one = '#051E3D', color_two = '#BC1A2D', conference = 'NL', division = 'East',
    stadium_lat = 33.890000, stadium_long = -84.468000 WHERE id = 13;  -- ATL Braves
UPDATE teams SET color_one = '#000000', color_two = '#00A4E1', conference = 'NL', division = 'East',
    stadium_lat = 25.778056, stadium_long = -80.219722 WHERE id = 6;   -- MIA Marlins
UPDATE teams SET color_one = '#002973', color_two = '#FF5908', conference = 'NL', division = 'East',
    stadium_lat = 40.756944, stadium_long = -73.845833 WHERE id = 1;   -- NYM Mets
UPDATE teams SET color_one = '#E91123', color_two = '#FFFFFF', conference = 'NL', division = 'East',
    stadium_lat = 39.905833, stadium_long = -75.166389 WHERE id = 23;  -- PHI Phillies
UPDATE teams SET color_one = '#AC0000', color_two = '#0C214A', conference = 'NL', division = 'East',
    stadium_lat = 38.872778, stadium_long = -77.007500 WHERE id = 30;  -- WAS Nationals

-- NL Central
UPDATE teams SET color_one = '#063087', color_two = '#CD3130', conference = 'NL', division = 'Central',
    stadium_lat = 41.948056, stadium_long = -87.655556 WHERE id = 22;  -- CHC Cubs
UPDATE teams SET color_one = '#C70019', color_two = '#000000', conference = 'NL', division = 'Central',
    stadium_lat = 39.097500, stadium_long = -84.506667 WHERE id = 29;  -- CIN Reds
UPDATE teams SET color_one = '#0A234A', color_two = '#FFC62B', conference = 'NL', division = 'Central',
    stadium_lat = 43.028333, stadium_long = -87.971111 WHERE id = 10;  -- MIL Brewers
UPDATE teams SET color_one = '#000000', color_two = '#FDB922', conference = 'NL', division = 'Central',
    stadium_lat = 40.446944, stadium_long = -80.005833 WHERE id = 7;   -- PIT Pirates
UPDATE teams SET color_one = '#B81B21', color_two = '#0C214A', conference = 'NL', division = 'Central',
    stadium_lat = 38.622500, stadium_long = -90.193056 WHERE id = 24;  -- STL Cardinals

-- NL West
UPDATE teams SET color_one = '#A8122C', color_two = '#3CC2CE', conference = 'NL', division = 'West',
    stadium_lat = 33.445278, stadium_long = -112.066944 WHERE id = 9;   -- ARI Diamondbacks
UPDATE teams SET color_one = '#503E80', color_two = '#000000', conference = 'NL', division = 'West',
    stadium_lat = 39.756111, stadium_long = -104.994167 WHERE id = 15;  -- COL Rockies
UPDATE teams SET color_one = '#023585', color_two = '#FFFFFF', conference = 'NL', division = 'West',
    stadium_lat = 34.073611, stadium_long = -118.240000 WHERE id = 27;  -- LAD Dodgers
UPDATE teams SET color_one = '#3C2E29', color_two = '#FEC729', conference = 'NL', division = 'West',
    stadium_lat = 32.707300, stadium_long = -117.156600 WHERE id = 28;  -- SD Padres
UPDATE teams SET color_one = '#000000', color_two = '#FD5A18', conference = 'NL', division = 'West',
    stadium_lat = 37.778611, stadium_long = -122.389167 WHERE id = 17;  -- SF Giants

-- ============================================================
-- AAA (level 8) — colors + coordinates
-- ============================================================
UPDATE teams SET color_one = '#002C5B', color_two = '#960530', stadium_lat = 41.360406, stadium_long = -75.683967 WHERE id = 61;   -- SCRA RailRiders
UPDATE teams SET color_one = '#000000', color_two = '#980029', stadium_lat = 38.580372, stadium_long = -121.513800 WHERE id = 62;   -- SACR River Cats
UPDATE teams SET color_one = '#002A5C', color_two = '#E31837', stadium_lat = 47.238033, stadium_long = -122.497544 WHERE id = 63;   -- TACO Rainiers
UPDATE teams SET color_one = '#000000', color_two = '#D61042', stadium_lat = 31.759028, stadium_long = -106.492667 WHERE id = 64;   -- PASO Chihuahuas
UPDATE teams SET color_one = '#EF2D1F', color_two = '#000000', stadium_lat = 43.158267, stadium_long = -77.619794 WHERE id = 65;   -- ROCH Red Wings
UPDATE teams SET color_one = '#E41134', color_two = '#000000', stadium_lat = 39.765000, stadium_long = -86.168333 WHERE id = 66;   -- INDI Indians
UPDATE teams SET color_one = '#0052A0', color_two = '#FFFFFF', stadium_lat = 44.950861, stadium_long = -93.084194 WHERE id = 67;   -- STPS Saints
UPDATE teams SET color_one = '#CF093F', color_two = '#0053A5', stadium_lat = 42.881306, stadium_long = -78.874278 WHERE id = 68;   -- BUFF Bisons
UPDATE teams SET color_one = '#000000', color_two = '#F2B22A', stadium_lat = 40.549700, stadium_long = -112.022500 WHERE id = 69;   -- SALT Bees
UPDATE teams SET color_one = '#001E4B', color_two = '#0078BC', stadium_lat = 30.324968, stadium_long = -81.643069 WHERE id = 70;   -- JAX Jumbo Shrimp
UPDATE teams SET color_one = '#0054A7', color_two = '#B25C0A', stadium_lat = 35.991689, stadium_long = -78.904186 WHERE id = 71;   -- DURH Bulls
UPDATE teams SET color_one = '#062037', color_two = '#20C9D1', stadium_lat = 29.622751, stadium_long = -95.647179 WHERE id = 72;   -- SLSC Space Cowboys
UPDATE teams SET color_one = '#005497', color_two = '#E41234', stadium_lat = 41.580278, stadium_long = -93.615833 WHERE id = 73;   -- IOWA Cubs
UPDATE teams SET color_one = '#000000', color_two = '#BE0F34', stadium_lat = 35.069722, stadium_long = -106.629167 WHERE id = 74;   -- ALBQ Isotopes
UPDATE teams SET color_one = '#011747', color_two = '#C9072A', stadium_lat = 36.172778, stadium_long = -86.784722 WHERE id = 75;   -- NASH Sounds
UPDATE teams SET color_one = '#051D42', color_two = '#A71933', stadium_lat = 30.527300, stadium_long = -97.630500 WHERE id = 76;   -- RRE Express
UPDATE teams SET color_one = '#122E5B', color_two = '#C91447', stadium_lat = 41.648333, stadium_long = -83.538889 WHERE id = 77;   -- TOL Mud Hens
UPDATE teams SET color_one = '#0A1C33', color_two = '#74AA50', stadium_lat = 34.040583, stadium_long = -83.992389 WHERE id = 78;   -- GWIN Stripers
UPDATE teams SET color_one = '#1F4991', color_two = '#B79353', stadium_lat = 41.151806, stadium_long = -96.106472 WHERE id = 79;   -- OMA Storm Chasers
UPDATE teams SET color_one = '#005DAA', color_two = '#8AC4E7', stadium_lat = 35.464961, stadium_long = -97.508050 WHERE id = 80;   -- OCBC Baseball Club
UPDATE teams SET color_one = '#002B5C', color_two = '#A4D7F4', stadium_lat = 39.968619, stadium_long = -83.010743 WHERE id = 81;   -- COLU Clippers
-- Oakland AAA (unmatched by script — manual)
UPDATE teams SET color_one = '#0C2340', color_two = '#FC4C02', stadium_lat = 36.152278, stadium_long = -115.329417 WHERE id = 82;   -- LVAV Aviators
UPDATE teams SET color_one = '#182A56', color_two = '#D61042', stadium_lat = 35.143056, stadium_long = -90.049167 WHERE id = 83;   -- MEMP Redbirds
UPDATE teams SET color_one = '#000000', color_two = '#00AEDB', stadium_lat = 35.227988, stadium_long = -80.849011 WHERE id = 84;   -- CHAR Knights
UPDATE teams SET color_one = '#EB142A', color_two = '#0D1C37', stadium_lat = 38.256186, stadium_long = -85.744653 WHERE id = 85;   -- LOU Bats
UPDATE teams SET color_one = '#002D62', color_two = '#C41230', stadium_lat = 40.626111, stadium_long = -75.452500 WHERE id = 86;   -- LVAL IronPigs
UPDATE teams SET color_one = '#002344', color_two = '#D02138', stadium_lat = 42.256944, stadium_long = -71.800000 WHERE id = 87;   -- WORS Red Sox
UPDATE teams SET color_one = '#004A90', color_two = '#F37F2D', stadium_lat = 43.079078, stadium_long = -76.165358 WHERE id = 88;   -- SYRA Mets
UPDATE teams SET color_one = '#002A5C', color_two = '#FFFFFF', stadium_lat = 39.529000, stadium_long = -119.808000 WHERE id = 89;   -- RENO Aces
UPDATE teams SET color_one = '#00A260', color_two = '#000000', stadium_lat = 36.842789, stadium_long = -76.278869 WHERE id = 90;   -- NOR Tides

-- ============================================================
-- AA (level 7) — colors + coordinates
-- ============================================================
UPDATE teams SET color_one = '#0D0702', color_two = '#D30A3F', stadium_lat = 33.507630, stadium_long = -86.810218 WHERE id = 31;   -- BIRM Barons
UPDATE teams SET color_one = '#D40943', color_two = '#000000', stadium_lat = 37.211111, stadium_long = -93.279722 WHERE id = 32;   -- SPRF Cardinals
UPDATE teams SET color_one = '#EF3741', color_two = '#1E191A', stadium_lat = 35.054444, stadium_long = -85.313889 WHERE id = 33;   -- CHAT Lookouts
UPDATE teams SET color_one = '#000000', color_two = '#F48B6D', stadium_lat = 32.452348, stadium_long = -84.991541 WHERE id = 34;   -- MISS Braves
UPDATE teams SET color_one = '#D21045', color_two = '#002D62', stadium_lat = 40.365833, stadium_long = -75.933611 WHERE id = 35;   -- READ Fightin Phils
-- Oakland AA (unmatched by script — manual)
UPDATE teams SET color_one = '#0B2240', color_two = '#F4911D', stadium_lat = 31.987332, stadium_long = -102.155799 WHERE id = 36;   -- MID RockHounds
UPDATE teams SET color_one = '#002E63', color_two = '#E1373C', stadium_lat = 43.656944, stadium_long = -70.278333 WHERE id = 37;   -- PORT Sea Dogs
UPDATE teams SET color_one = '#BA0C2F', color_two = '#010101', stadium_lat = 34.755215, stadium_long = -92.272582 WHERE id = 38;   -- ARKT Travelers
UPDATE teams SET color_one = '#00539B', color_two = '#002D62', stadium_lat = 30.404333, stadium_long = -87.218222 WHERE id = 39;   -- PENS Blue Wahoos
UPDATE teams SET color_one = '#D8183C', color_two = '#FFC70B', stadium_lat = 36.159167, stadium_long = -94.195000 WHERE id = 40;   -- NWAN Naturals
UPDATE teams SET color_one = '#002A5C', color_two = '#E51937', stadium_lat = 37.681389, stadium_long = -97.345833 WHERE id = 41;   -- WICH Wind Surge
UPDATE teams SET color_one = '#061B3D', color_two = '#C5062E', stadium_lat = 42.102769, stadium_long = -75.904988 WHERE id = 42;   -- BING Rumble Ponies
UPDATE teams SET color_one = '#4F90CC', color_two = '#C6CFD4', stadium_lat = 27.809583, stadium_long = -97.399694 WHERE id = 43;   -- CCH Hooks
UPDATE teams SET color_one = '#D40742', color_two = '#002962', stadium_lat = 40.256428, stadium_long = -76.889977 WHERE id = 44;   -- HARR Senators
UPDATE teams SET color_one = '#98012E', color_two = '#005395', stadium_lat = 33.098333, stadium_long = -96.820000 WHERE id = 45;   -- FRSC RoughRiders
UPDATE teams SET color_one = '#B60A14', color_two = '#1E191A', stadium_lat = 40.473611, stadium_long = -78.394722 WHERE id = 46;   -- ALTO Curve
UPDATE teams SET color_one = '#0068B3', color_two = '#F6D39D', stadium_lat = 30.395741, stadium_long = -88.893463 WHERE id = 47;   -- BILX Shuckers
UPDATE teams SET color_one = '#D5073F', color_two = '#1E191A', stadium_lat = 37.571806, stadium_long = -77.463733 WHERE id = 48;   -- RICH Flying Squirrels
UPDATE teams SET color_one = '#231F20', color_two = '#0779DC', stadium_lat = 41.077924, stadium_long = -81.522202 WHERE id = 49;   -- AKRD RubberDucks
UPDATE teams SET color_one = '#005696', color_two = '#6597C6', stadium_lat = 35.972213, stadium_long = -83.914381 WHERE id = 50;   -- TENN Smokies
UPDATE teams SET color_one = '#000000', color_two = '#F47E2D', stadium_lat = 38.945556, stadium_long = -76.709167 WHERE id = 51;   -- BOW Baysox
UPDATE teams SET color_one = '#0067B1', color_two = '#231F20', stadium_lat = 36.159722, stadium_long = -95.988056 WHERE id = 52;   -- TULS Drillers
UPDATE teams SET color_one = '#004A8E', color_two = '#00A260', stadium_lat = 41.771389, stadium_long = -72.673889 WHERE id = 53;   -- HART Yard Goats
UPDATE teams SET color_one = '#002B5C', color_two = '#E31837', stadium_lat = 42.980833, stadium_long = -71.466667 WHERE id = 54;   -- NHFC Fisher Cats
UPDATE teams SET color_one = '#002D62', color_two = '#CAA879', stadium_lat = 29.409131, stadium_long = -98.601114 WHERE id = 55;   -- SA Missions
UPDATE teams SET color_one = '#113C6D', color_two = '#EFA900', stadium_lat = 35.205778, stadium_long = -101.830972 WHERE id = 56;  -- AMAR Sod Poodles
UPDATE teams SET color_one = '#1E191A', color_two = '#D40A43', stadium_lat = 42.126944, stadium_long = -80.080000 WHERE id = 57;   -- ERIE SeaWolves
UPDATE teams SET color_one = '#EF3C40', color_two = '#007EC4', stadium_lat = 34.683883, stadium_long = -86.724288 WHERE id = 58;   -- RCTP Trash Pandas
UPDATE teams SET color_one = '#003263', color_two = '#900028', stadium_lat = 40.560556, stadium_long = -74.553056 WHERE id = 59;   -- SMST Patriots
UPDATE teams SET color_one = '#000E35', color_two = '#EFB209', stadium_lat = 32.382200, stadium_long = -86.310600 WHERE id = 60;   -- MONT Biscuits

-- ============================================================
-- High-A (level 6) — colors + coordinates
-- ============================================================
UPDATE teams SET color_one = '#D40943', color_two = '#002962', stadium_lat = 47.662000, stadium_long = -117.345000 WHERE id = 91;   -- SPOK Indians
UPDATE teams SET color_one = '#002962', color_two = '#D0AC7B', stadium_lat = 46.267000, stadium_long = -119.172000 WHERE id = 92;   -- TCDD Dust Devils
UPDATE teams SET color_one = '#009DDC', color_two = '#EF4035', stadium_lat = 42.497639, stadium_long = -89.040083 WHERE id = 93;   -- BELT Sky Carp
UPDATE teams SET color_one = '#E12F29', color_two = '#E12F29', stadium_lat = 40.687500, stadium_long = -89.597500 WHERE id = 94;   -- PEOR Chiefs
UPDATE teams SET color_one = '#860038', color_two = '#860038', stadium_lat = 44.283524, stadium_long = -88.468742 WHERE id = 95;   -- WISC Timber Rattlers
UPDATE teams SET color_one = '#005798', color_two = '#E41937', stadium_lat = 41.670394, stadium_long = -86.255478 WHERE id = 96;   -- SBC Cubs
UPDATE teams SET color_one = '#002B5E', color_two = '#7AC142', stadium_lat = 34.945000, stadium_long = -81.935833 WHERE id = 97;   -- HICK Crawdads
-- Oakland High-A (unmatched by script — manual)
UPDATE teams SET color_one = '#E61234', color_two = '#C7D0D5', stadium_lat = 42.734722, stadium_long = -84.545278 WHERE id = 98;   -- LANS Lugnuts
UPDATE teams SET color_one = '#004A8D', color_two = '#004A8D', stadium_lat = 40.574444, stadium_long = -73.984167 WHERE id = 99;   -- BRKN Cyclones
UPDATE teams SET color_one = '#002D62', color_two = '#00BCE4', stadium_lat = 47.967000, stadium_long = -122.203000 WHERE id = 100;  -- EVAS AquaSox
UPDATE teams SET color_one = '#96C0E6', color_two = '#002D62', stadium_lat = 39.732222, stadium_long = -75.564444 WHERE id = 101;  -- WILM Blue Rocks
UPDATE teams SET color_one = '#00529C', color_two = '#00529C', stadium_lat = 39.530873, stadium_long = -76.185985 WHERE id = 102;  -- ABER IronBirds
UPDATE teams SET color_one = '#231F20', color_two = '#008265', stadium_lat = 44.059000, stadium_long = -123.066000 WHERE id = 103;  -- EUGE Emeralds
UPDATE teams SET color_one = '#C20F2F', color_two = '#0D1D41', stadium_lat = 40.075100, stadium_long = -74.187000 WHERE id = 104;  -- JSHO BlueClaws
UPDATE teams SET color_one = '#002349', color_two = '#FF6C1C', stadium_lat = 36.996778, stadium_long = -86.440906 WHERE id = 105;  -- BGHR Hot Rods
UPDATE teams SET color_one = '#0D4000', color_two = '#EE2A24', stadium_lat = 41.074056, stadium_long = -85.142861 WHERE id = 106;  -- FWTC Tin Caps
UPDATE teams SET color_one = '#1F3658', color_two = '#2C437C', stadium_lat = 43.040195, stadium_long = -85.659832 WHERE id = 107;  -- WMW Whitecaps
UPDATE teams SET color_one = '#562E8F', color_two = '#000000', stadium_lat = 36.091602, stadium_long = -80.255962 WHERE id = 108;  -- WISA Dash
UPDATE teams SET color_one = '#005695', color_two = '#005695', stadium_lat = 35.587222, stadium_long = -82.549167 WHERE id = 109;  -- ASHV Tourists
UPDATE teams SET color_one = '#008752', color_two = '#F68B1E', stadium_lat = 36.076667, stadium_long = -79.794722 WHERE id = 110;  -- GRBR Grasshoppers
UPDATE teams SET color_one = '#000000', color_two = '#008044', stadium_lat = 39.764167, stadium_long = -84.185000 WHERE id = 111;  -- DAYT Dragons
UPDATE teams SET color_one = '#002955', color_two = '#002955', stadium_lat = 45.554000, stadium_long = -122.908500 WHERE id = 112;  -- HILL Hops
UPDATE teams SET color_one = '#FFC520', color_two = '#FFC520', stadium_lat = 41.968056, stadium_long = -91.686389 WHERE id = 113;  -- CRK Kernels
UPDATE teams SET color_one = '#231F20', color_two = '#FE3224', stadium_lat = 34.285833, stadium_long = -85.167222 WHERE id = 114;  -- ROME Emperors
UPDATE teams SET stadium_lat = 43.609169, stadium_long = -84.236703 WHERE id = 115;  -- GLL Loons (no colors in source)
UPDATE teams SET color_one = '#AF272F', color_two = '#010101', stadium_lat = 41.641111, stadium_long = -81.435556 WHERE id = 116;  -- LCC Captains
UPDATE teams SET color_one = '#00549D', color_two = '#00549D', stadium_lat = 41.518669, stadium_long = -90.582242 WHERE id = 117;  -- QCRB River Bandits
UPDATE teams SET color_one = '#D71932', color_two = '#848689', stadium_lat = 34.842200, stadium_long = -82.408200 WHERE id = 118;  -- GRNV Drive
UPDATE teams SET color_one = '#002A5B', color_two = '#0096D6', stadium_lat = 41.527911, stadium_long = -73.961067 WHERE id = 119;  -- HUDV Renegades
UPDATE teams SET color_one = '#ED174F', color_two = '#FFFFFF', stadium_lat = 49.243100, stadium_long = -123.106300 WHERE id = 120;  -- VANC Canadiens

-- ============================================================
-- Single-A (level 5) — colors + coordinates
-- ============================================================
UPDATE teams SET color_one = '#000000', color_two = '#E61A30', stadium_lat = 33.654167, stadium_long = -117.301944 WHERE id = 151;  -- LELS Storm
UPDATE teams SET color_one = '#000000', color_two = '#F2652D', stadium_lat = 38.369722, stadium_long = -75.529444 WHERE id = 152;  -- DMRV Shorebirds
UPDATE teams SET color_one = '#EC0928', color_two = '#000000', stadium_lat = 35.749167, stadium_long = -81.378611 WHERE id = 153;  -- DEWD Wood Ducks
UPDATE teams SET color_one = '#002A5C', color_two = '#DC791C', stadium_lat = 28.074722, stadium_long = -81.950833 WHERE id = 154;  -- LAKE Flying Tigers
UPDATE teams SET color_one = '#231F20', color_two = '#D41548', stadium_lat = 36.332500, stadium_long = -119.304722 WHERE id = 155;  -- VLIA Rawhide
UPDATE teams SET color_one = '#132D5D', color_two = '#DAE502', stadium_lat = 34.017417, stadium_long = -81.031397 WHERE id = 156;  -- CFF Fireflies
UPDATE teams SET color_one = '#0D2345', color_two = '#00B3AD', stadium_lat = 37.392816, stadium_long = -79.165623 WHERE id = 157;  -- LHBC Hillcats
UPDATE teams SET color_one = '#000000', color_two = '#0081C6', stadium_lat = 26.891111, stadium_long = -80.116389 WHERE id = 158;  -- JUPI Hammerheads
UPDATE teams SET color_one = '#0071BA', color_two = '#FFC427', stadium_lat = 33.711682, stadium_long = -78.884500 WHERE id = 159;  -- MBP Pelicans
UPDATE teams SET color_one = '#C21F33', color_two = '#000000', stadium_lat = 36.732100, stadium_long = -119.790500 WHERE id = 160;  -- FRES Grizzlies
UPDATE teams SET color_one = '#F47835', color_two = '#221E1F', stadium_lat = 37.320556, stadium_long = -121.862222 WHERE id = 161;  -- JOSE Giants
UPDATE teams SET color_one = '#000000', color_two = '#C42032', stadium_lat = 35.055914, stadium_long = -78.883382 WHERE id = 162;  -- FYTV Woodpeckers
UPDATE teams SET color_one = '#EE3A43', color_two = '#000000', stadium_lat = 35.817222, stadium_long = -78.270000 WHERE id = 163;  -- CARO Mudcats
-- Oakland Single-A (unmatched by script — manual)
UPDATE teams SET color_one = '#E31736', color_two = '#FFFFFF', stadium_lat = 37.954856, stadium_long = -121.297956 WHERE id = 164;  -- STCK Ports
UPDATE teams SET color_one = '#D31145', color_two = '#005695', stadium_lat = 27.971667, stadium_long = -82.731667 WHERE id = 165;  -- CWAT Threshers
UPDATE teams SET color_one = '#005847', color_two = '#97C0E6', stadium_lat = 29.209444, stadium_long = -81.016667 WHERE id = 166;  -- TONA Tortugas
UPDATE teams SET color_one = '#004B8D', color_two = '#F47D30', stadium_lat = 27.325281, stadium_long = -80.404494 WHERE id = 167;  -- STLM Mets
UPDATE teams SET color_one = '#121D35', color_two = '#F6A607', stadium_lat = 32.790278, stadium_long = -79.961111 WHERE id = 168;  -- CHST RiverDogs
UPDATE teams SET color_one = '#194076', color_two = '#E32128', stadium_lat = 35.499167, stadium_long = -80.626667 WHERE id = 169;  -- KANN Cannon Ballers
UPDATE teams SET color_one = '#D31245', color_two = '#FFFFFF', stadium_lat = 38.318056, stadium_long = -77.509722 WHERE id = 170;  -- FRED Nationals
UPDATE teams SET color_one = '#081F2C', color_two = '#98A4AE', stadium_lat = 27.980278, stadium_long = -82.506667 WHERE id = 171;  -- TAMP Tarpons
UPDATE teams SET color_one = '#001A38', color_two = '#6756A5', stadium_lat = 26.538333, stadium_long = -81.841944 WHERE id = 172;  -- FMMM Mighty Mussels
UPDATE teams SET color_one = '#003DA5', color_two = '#FFFFFF', stadium_lat = 28.003611, stadium_long = -82.786389 WHERE id = 173;  -- DUNE Blue Jays
UPDATE teams SET color_one = '#007954', color_two = '#76BD1A', stadium_lat = 33.483889, stadium_long = -81.973889 WHERE id = 174;  -- AUGU Green Jackets
UPDATE teams SET color_one = '#B40235', color_two = '#E7BC84', stadium_lat = 37.622658, stadium_long = -121.000814 WHERE id = 175;  -- MOD Nuts
UPDATE teams SET color_one = '#231F20', color_two = '#FFC425', stadium_lat = 27.485833, stadium_long = -82.570278 WHERE id = 176;  -- BRAD Marauders
UPDATE teams SET color_one = '#7ABEE9', color_two = '#F47933', stadium_lat = 34.097222, stadium_long = -117.295278 WHERE id = 177;  -- IESS 66ers
UPDATE teams SET color_one = '#D31245', color_two = '#002B5C', stadium_lat = 26.891111, stadium_long = -80.116389 WHERE id = 178;  -- PALM Cardinals
UPDATE teams SET color_one = '#E31837', color_two = '#0C2340', stadium_lat = 37.285278, stadium_long = -80.036667 WHERE id = 179;  -- SALM Red Sox
UPDATE teams SET color_one = '#CFAB7A', color_two = '#192C40', stadium_lat = 34.102765, stadium_long = -117.547970 WHERE id = 180;  -- RCQ Quakes

-- ============================================================
-- Scraps (level 4) — inherit MLB org colors, no coordinates
-- ============================================================
UPDATE teams SET color_one = '#002973', color_two = '#FF5908' WHERE id = 121;  -- NYM scraps
UPDATE teams SET color_one = '#002E79', color_two = '#C10919' WHERE id = 122;  -- TEX scraps
UPDATE teams SET color_one = '#042855', color_two = '#FF4713' WHERE id = 123;  -- DET scraps
UPDATE teams SET color_one = '#002962', color_two = '#EC6E19' WHERE id = 124;  -- HOU scraps
UPDATE teams SET color_one = '#0B1F46', color_two = '#FFFFFF' WHERE id = 125;  -- NYY scraps
UPDATE teams SET color_one = '#000000', color_two = '#00A4E1' WHERE id = 126;  -- MIA scraps
UPDATE teams SET color_one = '#000000', color_two = '#FDB922' WHERE id = 127;  -- PIT scraps
UPDATE teams SET color_one = '#0B498F', color_two = '#17295C' WHERE id = 128;  -- TOR scraps
UPDATE teams SET color_one = '#A8122C', color_two = '#3CC2CE' WHERE id = 129;  -- ARI scraps
UPDATE teams SET color_one = '#0A234A', color_two = '#FFC62B' WHERE id = 130;  -- MIL scraps
UPDATE teams SET color_one = '#02285C', color_two = '#90BDE7' WHERE id = 131;  -- TB scraps
UPDATE teams SET color_one = '#051E3D', color_two = '#BC1A2D' WHERE id = 132;  -- ATL scraps
UPDATE teams SET color_one = '#CE093F', color_two = '#002E63' WHERE id = 133;  -- LAA scraps
UPDATE teams SET color_one = '#00352D', color_two = '#EFB318' WHERE id = 134;  -- OAK scraps
UPDATE teams SET color_one = '#503E80', color_two = '#000000' WHERE id = 135;  -- COL scraps
UPDATE teams SET color_one = '#1E191A', color_two = '#FFFFFF' WHERE id = 136;  -- CWS scraps
UPDATE teams SET color_one = '#000000', color_two = '#FD5A18' WHERE id = 137;  -- SF scraps
UPDATE teams SET color_one = '#004488', color_two = '#FFFFFF' WHERE id = 138;  -- KC scraps
UPDATE teams SET color_one = '#E41831', color_two = '#02193E' WHERE id = 139;  -- MIN scraps
UPDATE teams SET color_one = '#BE2C36', color_two = '#052755' WHERE id = 140;  -- BOS scraps
UPDATE teams SET color_one = '#06203F', color_two = '#C90628' WHERE id = 141;  -- CLE scraps
UPDATE teams SET color_one = '#063087', color_two = '#CD3130' WHERE id = 142;  -- CHC scraps
UPDATE teams SET color_one = '#E91123', color_two = '#FFFFFF' WHERE id = 143;  -- PHI scraps
UPDATE teams SET color_one = '#B81B21', color_two = '#0C214A' WHERE id = 144;  -- STL scraps
UPDATE teams SET color_one = '#042855', color_two = '#C5CFD5' WHERE id = 145;  -- SEA scraps
UPDATE teams SET color_one = '#000000', color_two = '#E04400' WHERE id = 146;  -- BAL scraps
UPDATE teams SET color_one = '#023585', color_two = '#FFFFFF' WHERE id = 147;  -- LAD scraps
UPDATE teams SET color_one = '#3C2E29', color_two = '#FEC729' WHERE id = 148;  -- SD scraps
UPDATE teams SET color_one = '#C70019', color_two = '#000000' WHERE id = 149;  -- CIN scraps
UPDATE teams SET color_one = '#AC0000', color_two = '#0C214A' WHERE id = 150;  -- WAS scraps
