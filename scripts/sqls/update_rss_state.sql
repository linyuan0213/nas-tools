-- 更新所有电影订阅状态为R（仅当状态为S时）
UPDATE RSS_MOVIES SET STATE = 'R' WHERE STATE = 'S';

-- 更新所有电视剧订阅状态为R（仅当状态为S时）
UPDATE RSS_TVS SET STATE = 'R' WHERE STATE = 'S';
