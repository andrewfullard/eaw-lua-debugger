from eaw_lua_debugger.client import ScriptInfo
from eaw_lua_debugger.gui_sources import format_source_lines, load_script_source


def test_load_script_source_uses_data_scripts_suffix(tmp_path):
    source_path = tmp_path / "Data" / "Scripts" / "Foo.lua"
    source_path.parent.mkdir(parents=True)
    source_path.write_text("print('ok')\n", encoding="utf-8")

    source = load_script_source(
        ScriptInfo(7, "C:/Build/Data/Scripts/Foo.lua"),
        [tmp_path],
    )

    assert source.found is True
    assert source.path == source_path
    assert source.text == "print('ok')\n"


def test_format_source_lines_includes_line_numbers_and_breakpoint_markers():
    assert format_source_lines("a\nb\n", {2}) == "  1   a\n  2 \u25cf b"
