"""Long messages are matched by their question pieces: the splitter keeps the question and drops the story."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[0] / "bot"))
import segment as sg  # noqa: E402


def test_the_question_is_found_inside_a_story():
    msg = "Hi there, I run a small blog about packaged foods and have been looking for a dataset for months, so my question is does the monthly download include every field"
    assert sg.question_pieces(msg) == ["does the monthly download include every field"]
    assert sg.question_pieces("so um i read about the checks and i just wanna know like are those checking for typos or impossible values") == ["are those checking for typos or impossible values"]


def test_short_messages_are_not_split_and_a_story_without_a_question_gives_no_pieces():
    assert not sg.is_long("how often is the data updated")
    assert sg.question_pieces("I have been using food data for years and found this site last week by accident and wanted to say hello") == []
