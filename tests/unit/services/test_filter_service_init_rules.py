"""FilterService 内置规则组解析单元测试"""

from pathlib import Path

from app.services.filter_service import FilterService

SQL_FILE = Path(__file__).parents[3] / "src/app/db/data/init_filter.sql"


class TestLoadInitRuleGroups:
    def test_parses_all_groups(self):
        groups = FilterService._load_init_rule_groups(str(SQL_FILE))
        ids = [g["id"] for g in groups]
        assert ids == [1000, 1001, 1002, 9999]

    def test_group_names_and_rules(self):
        groups = {g["id"]: g for g in FilterService._load_init_rule_groups(str(SQL_FILE))}
        assert groups[1002]["name"] == "中字"
        assert len(groups[1002]["rules"]) == 3
        assert groups[9999]["name"] == "不过滤"
        assert groups[9999]["rules"] == []

    def test_rule_fields_parsed_correctly(self):
        groups = {g["id"]: g for g in FilterService._load_init_rule_groups(str(SQL_FILE))}
        first = groups[1002]["rules"][0]
        assert first["name"] == "4k中字"
        assert "(?:简体" in first["include"]
        assert "4k|2160p" in first["include"]
        assert "Blu-?Ray" in first["exclude"]

    def test_sql_chunks_preserved_for_restore(self):
        groups = FilterService._load_init_rule_groups(str(SQL_FILE))
        for group in groups:
            assert group["sql"]
            assert "INSERT" in group["sql"][0].upper()
        group_1002 = next(g for g in groups if g["id"] == 1002)
        assert len(group_1002["sql"]) == 2
        assert "CONFIG_FILTER_RULES" in group_1002["sql"][1].upper()
