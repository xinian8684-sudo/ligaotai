from helpers import make_chapters

from tools.eval_dedup import run_eval
from tools.scramble import scramble


def test_end_to_end_recall_on_synthetic_book(tmp_path):
    out = tmp_path / "乱稿"
    key = scramble(
        make_chapters(20), out, seed=3,
        n_delete=2, n_truncate=2, n_full=3, n_excerpt=2, alias_chapters=5,
    )
    report = run_eval(out, key, tmp_path / "书库")
    assert report["variants"] == 5
    assert report["recall"] == 1.0, report["missed"]
    assert report["cross_chapter_groups"] == []
    assert report["pass"] is True
    assert report["scenes"] > 0
