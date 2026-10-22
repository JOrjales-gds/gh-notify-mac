from gh_notify.config import (
    DEFAULT_POLL_INTERVAL_S,
    MIN_POLL_INTERVAL_S,
    Config,
    load_config,
)


def write(tmp_path, text):
    path = tmp_path / "config.toml"
    path.write_text(text)
    return path


def test_missing_file_gives_defaults(tmp_path):
    assert load_config(tmp_path / "nope.toml") == Config()


def test_values_are_read(tmp_path):
    path = write(
        tmp_path,
        'poll_interval = 120\nreplies = false\nignore_authors = ["Bob"]\ngh_path = "/x/gh"\n',
    )
    config = load_config(path)
    assert (config.poll_interval, config.replies, config.mentions) == (120, False, True)
    assert config.ignore_authors == ["bob"]
    assert config.gh_path == "/x/gh"


def test_interval_has_a_floor(tmp_path):
    assert (
        load_config(write(tmp_path, "poll_interval = 1\n")).poll_interval
        == MIN_POLL_INTERVAL_S
    )


def test_wrong_types_and_bad_toml_fall_back(tmp_path):
    path = write(
        tmp_path, 'poll_interval = "fast"\nreplies = "no"\nignore_authors = [1]\n'
    )
    config = load_config(path)
    assert config.poll_interval == DEFAULT_POLL_INTERVAL_S
    assert config.replies is True and config.ignore_authors == []
    assert load_config(write(tmp_path, "not = [valid")) == Config()
